"""Lógica de reprodução: o que toca, o que vem depois, shuffle/repeat e recuperação de erros.

Fontes de reprodução (`source`):
  ("queue", None)      fila temporária
  ("playlist", id)     uma playlist
  ("list", [faixas])   uma lista qualquer (resultados da busca, seção da Home…)
"""
import random
import threading
import time

from .logger import log
from .utils import fmt_time


class PlaybackController:
    MAX_RETRIES = 3

    def __init__(self, app):
        self.app = app
        self.audio = app.audio
        self.youtube = app.youtube

        self.title = "—"
        self.url = ""                 # url do vídeo tocando agora
        self.stream_url = None
        self.resolving_title = None   # título da faixa que está sendo carregada
        self.source = None
        self.index = -1

        self.shuffle = False
        self.repeat = "off"           # off | all | one
        self._order = []
        self._order_pos = 0

        self._req = 0                 # invalida resoluções antigas
        self._retry = 0
        self._recovering = False
        self._recover_pos = 0.0
        self._fail_streak = 0
        self._handled_end = -1
        self._handled_err = -1

    # ------------------------------------------------------------ iniciar faixas
    def play_list(self, items, idx):
        if 0 <= idx < len(items):
            self.play_item(items[idx], ("list", items), idx)

    def play_from(self, kind, pid, idx):
        source = (kind, pid)
        tracks = self._tracks(source)
        if 0 <= idx < len(tracks):
            self.play_item(tracks[idx], source, idx)

    def play_item(self, item, source=None, index=-1, auto=False):
        """Resolve o áudio em segundo plano (a interface nunca trava esperando a rede)."""
        url = item.get("url")
        if not url:
            return
        self._req += 1
        req = self._req
        self._recovering = False
        self.resolving_title = item.get("title", "?")
        self.source, self.index = source, index
        self._sync_shuffle()

        def work():
            try:
                time.sleep(0.15)                         # segurou ">"? só a última faixa é resolvida
                if req != self._req:
                    return
                info = self.youtube.audio_info(url)
                if req != self._req:
                    return                               # usuário escolheu outra faixa
                self.resolving_title = None
                if not info.stream_url:
                    self._resolve_failed(info.error, auto)
                    return
                self._fail_streak = 0
                self._retry = 0
                self.url, self.stream_url = url, info.stream_url
                self.title = info.title or item.get("title", "?")
                if info.length:
                    item["duration"] = fmt_time(info.length)
                self.audio.open(info.stream_url, duration_hint=info.length)
                self.app.playlists.add_history(
                    {"title": self.title, "url": url, "duration": item.get("duration", "")},
                    limit=self.app.config.get("behavior", "history_limit", default=50))
                self.app.home.invalidate()
            except Exception as e:
                log(f"play_item: {e}")
                if req == self._req:
                    self.resolving_title = None
                    self.app.notify("erro ao carregar a faixa")

        threading.Thread(target=work, daemon=True, name="resolve").start()

    def _resolve_failed(self, error, auto):
        self.app.notify("live streams not supported" if error == "live"
                        else "could not resolve audio url")
        if auto and self.source:
            self._fail_streak += 1
            if self._fail_streak < 4:                    # pula faixa ruim, sem loop infinito
                self.next(auto=True)

    # ------------------------------------------------------------ navegação
    def _tracks(self, source):
        if not source:
            return []
        kind, ref = source
        if kind == "queue":
            return self.app.queue.tracks
        if kind == "playlist":
            pl = self.app.playlists.find(ref)
            return pl["tracks"] if pl else []
        if kind == "list":
            return ref
        return []

    def next(self, auto=False):
        tracks = self._tracks(self.source)
        if not tracks:
            if not auto:
                self.app.notify("nothing to skip to")
            return
        total = len(tracks)
        if self.shuffle:
            idx = self._shuffle_step(+1, total)
        else:
            idx = self.index + 1
            if idx >= total:
                idx = 0 if self.repeat == "all" else None
        if idx is None:
            self.app.notify("end of list")
            return
        self.play_item(tracks[idx], self.source, idx, auto=auto)

    def prev(self):
        tracks = self._tracks(self.source)
        if self.audio.time_pos > 3 or not tracks:
            self.audio.seek_to(0)                        # como nos players de verdade
            return
        total = len(tracks)
        if self.shuffle:
            idx = self._shuffle_step(-1, total)
        else:
            idx = self.index - 1
            if idx < 0:
                idx = total - 1 if self.repeat == "all" else None
        if idx is None:
            self.audio.seek_to(0)
            return
        self.play_item(tracks[idx], self.source, idx)

    # ------------------------------------------------------------ shuffle / repeat
    def toggle_shuffle(self):
        self.shuffle = not self.shuffle
        self._order = []
        self._sync_shuffle()
        self.app.notify(f"shuffle: {'on' if self.shuffle else 'off'}")

    def cycle_repeat(self):
        self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
        self.app.notify(f"repeat: {self.repeat}")

    def _sync_shuffle(self):
        """Mantém a ordem aleatória coerente com a faixa atual (ela vem primeiro)."""
        if not self.shuffle or not self.source:
            return
        total = len(self._tracks(self.source))
        if total == 0:
            return
        valid = 0 <= self.index < total
        if len(self._order) != total or (valid and self.index not in self._order):
            rest = [i for i in range(total) if i != self.index]
            random.shuffle(rest)
            self._order = ([self.index] if valid else []) + rest
        self._order_pos = self._order.index(self.index) if self.index in self._order else 0

    def _shuffle_step(self, delta, total):
        self._sync_shuffle()
        pos = self._order_pos + delta
        if pos >= total:
            if self.repeat != "all":
                return None
            random.shuffle(self._order)
            pos = 0
        elif pos < 0:
            if self.repeat != "all":
                return None
            pos = total - 1
        self._order_pos = pos
        return self._order[pos]

    # ------------------------------------------------------------ eventos do player
    def tick(self):
        a = self.audio
        if self._recovering or self.resolving_title:
            return
        if a.stage == "done" and self.url and self._handled_end != a.gen:
            self._handled_end = a.gen
            self._retry = 0
            if self.repeat == "one" and self.stream_url:
                a.open(self.stream_url, duration_hint=a.duration)
            else:
                self.next(auto=True)
        elif (a.stage == "error" and self.url and a.error_kind != "device"
              and self._handled_err != a.gen):
            self._handled_err = a.gen
            self._recover()
        elif a.stage == "streaming" and self._retry and a.time_pos - self._recover_pos > 20:
            self._retry = 0                              # voltou a tocar estável

    def _recover(self):
        """Erro de stream (URL expirou, rede caiu…): pega URL nova e retoma de onde parou."""
        self._retry += 1
        log(f"RECOVERY tentativa {self._retry}")
        if self._retry > self.MAX_RETRIES:
            self.app.notify("falha repetida — avançando")
            self._retry = 0
            self.next(auto=True)
            return
        self._recovering = True
        self._req += 1
        req = self._req
        pos = max(0.0, self.audio.time_pos - 2.0)
        url, attempt = self.url, self._retry

        def work():
            info = self.youtube.audio_info(url)
            if req != self._req:
                return
            self._recovering = False
            if not info.stream_url:
                self.app.notify("recovery: sem url nova")
                self.next(auto=True)
                return
            self.stream_url = info.stream_url
            self._recover_pos = pos
            self.audio.open(info.stream_url, start=pos, duration_hint=info.length)
            self.app.notify(f"retomando de {fmt_time(pos)} (tent. {attempt})")

        threading.Thread(target=work, daemon=True, name="recover").start()
