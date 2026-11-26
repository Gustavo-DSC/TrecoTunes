import core
core.reset_log()

import curses
import time
import threading
import sys
import random
import math
import os
import traceback
import numpy as np

from core import log, Theme, fmt_time, truncate, spinner_frame
from config_manager import ConfigManager
from playlist_manager import PlaylistManager
from queue_manager import QueueManager
from audio_controller import AudioController
from youtube_manager import YouTubeManager


def test_audio_device():
    import sounddevice as sd
    log("TESTE_DEVICE")
    try:
        sr = 44100
        t = np.linspace(0, 0.25, int(sr * 0.25), False)
        tone = (0.12 * np.sin(2 * np.pi * 660 * t)).astype(np.float32)
        with sd.OutputStream(samplerate=sr, channels=1,
                             dtype="float32", blocksize=4096) as out:
            out.write(np.ascontiguousarray(tone.reshape(-1, 1)))
        return True
    except Exception as e:
        log(f"TESTE_DEVICE FAIL: {e}")
        return False


class PlayerApp:
    S_MARK = "▸"
    S_DOT = "●"
    S_CIRCLE = "○"
    S_NOTE = "♫"
    S_PLAY = "▶"
    S_PAUSE = "❚❚"
    S_SEARCH = "⌕"
    VIZ = " ▁▂▃▄▅▆▇█"
    MAX_RETRIES = 3

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.config = ConfigManager()
        self.theme = Theme(self.config)
        self.playlists = PlaylistManager()
        self.queue = QueueManager()
        self.audio = AudioController()
        self.youtube = YouTubeManager()

        self.mode = "home"
        self.home_sections = []     # [(title, items)]
        self.search_results = []
        self.search_query = ""
        self.search_all_cache = []  # cache local pra infinite scroll
        self.search_shown = 0
        self.search_loading = False
        self.search_more_loading = False
        self._search_req_id = 0

        self.input_mode = False
        self.input_buffer = ""
        self._input_purpose = "search"
        self._rename_target = None

        self.running = True
        self.visualizer = [0.0] * 36
        self.current_title = "—"
        self.current_url = ""
        self.current_track_idx = -1
        self.current_source = None  # ("playlist", id) | ("queue", None)
        self.message = ""
        self._msg_time = 0.0

        self.selections = {"home": 0, "search": 0, "queue": 0}
        self.settings_cursor = 0
        self.playlist_focus = "list"
        self.playlist_cursor = 0
        self.track_cursor = 0

        # playback modes
        self.shuffle = False
        self.repeat = "off"  # off | all | one
        self.shuffle_order = []
        self.shuffle_pos = 0

        # retry
        self._retry_count = 0
        self._recovery_busy = False

        self._phase = 0.0
        threading.Thread(target=self._load_home, daemon=True).start()

    def _c(self, n, extra=0):
        return self.theme.pair(n) | extra

    # ---------------- HOME ----------------
    def _load_home(self):
        sections = []
        recent = self.playlists.get_history(limit=6)
        if recent:
            sections.append(("Recently Played", recent))
        active_pl = self.playlists.get_active()
        if active_pl and active_pl["tracks"]:
            continue_list = active_pl["tracks"][:6]
            sections.append((f"Continue · {active_pl['name']}", continue_list))
        # sections via rede (background)
        seed = recent[0]["title"] if recent else "lofi hip hop"
        for_query = f"{seed.split('·')[0].strip()[:30]} mix"
        foryou = self.youtube.search_initial(for_query, total=15)
        if foryou:
            sections.append(("For You", foryou[:6]))
        discover = self.youtube.search_initial("discover new music 2024", total=15)
        if discover:
            sections.append(("Discover", discover[:6]))
        if not sections:
            fallback = self.youtube.search_initial("lofi hip hop", total=15)
            if fallback:
                sections.append(("Recommended", fallback[:6]))
        self.home_sections = sections

    def _home_flat_items(self):
        flat = []
        for _, items in self.home_sections:
            flat.extend(items)
        return flat

    # ---------------- RUN ----------------
    def run(self):
        self.stdscr.nodelay(True)
        self.stdscr.keypad(True)
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.stdscr.timeout(50)
        self.theme.init()
        while self.running:
            try:
                self.draw()
            except Exception as e:
                log(f"draw: {e}\n{traceback.format_exc()}")
            try:
                key = self.stdscr.getch()
            except Exception:
                break
            if key != -1:
                try:
                    self.handle_key(key)
                except Exception as e:
                    log(f"key: {e}\n{traceback.format_exc()}")
                    self.message = "internal error"
                    self._msg_time = time.time()
            self._tick()
            self._animate()

    def _tick(self):
        # recuperação de erro
        if (self.audio._stage == "error" and not self._recovery_busy and
                self.current_url):
            self._attempt_recovery()
        # fim de faixa
        if (self.audio._stage == "done" and not self._recovery_busy and
                self.current_url and not self.audio.paused):
            self._on_track_end()
        # infinite scroll
        if (self.mode == "search" and not self.search_loading and
                not self.search_more_loading and self.search_shown < len(self.search_all_cache)):
            sel = self.selections["search"]
            if sel >= self.search_shown - 3:
                self._reveal_more()

    def _on_track_end(self):
        self._retry_count = 0
        if self.repeat == "one":
            self._replay_current()
            return
        self._advance_track(forward=True, from_end=True)

    def _attempt_recovery(self):
        self._recovery_busy = True
        self._retry_count += 1
        log(f"RECOVERY attempt {self._retry_count}")
        if self._retry_count > self.MAX_RETRIES:
            self.message = f"falha repetida — avançando"
            self._msg_time = time.time()
            self._retry_count = 0
            self._recovery_busy = False
            self.audio.error = None
            self._advance_track(forward=True, from_end=True)
            return
        last_pos = max(0.0, self.audio.time_pos - 2.0)
        url = self.current_url
        # refresca URL (pode ter expirado)
        audio_url, title, duration = self.youtube.get_audio_info(url)
        if not audio_url:
            self.message = "recovery: sem url nova"
            self._msg_time = time.time()
            self._recovery_busy = False
            self.audio.error = None
            self._advance_track(forward=True, from_end=True)
            return
        self.audio.error = None
        self.audio.load(audio_url)
        self.audio.seek_to(last_pos)
        self.audio.play()
        self.message = f"retomando de {fmt_time(last_pos)} (tent. {self._retry_count})"
        self._msg_time = time.time()
        self._recovery_busy = False

    def _replay_current(self):
        if not self.current_url:
            return
        audio_url, _, _ = self.youtube.get_audio_info(self.current_url)
        if audio_url:
            self.audio.load(audio_url)
            self.audio.play()

    def _advance_track(self, forward=True, from_end=False):
        source = self.current_source
        if not source:
            return
        kind, pid = source
        if kind == "queue":
            tracks = self.queue.tracks
            if not tracks:
                return
            if self.shuffle:
                next_idx = self._next_shuffle_idx(len(tracks))
                if next_idx is None:
                    return
            else:
                next_idx = self.current_track_idx + (1 if forward else -1)
                if next_idx < 0 or next_idx >= len(tracks):
                    if self.repeat == "all" and from_end:
                        next_idx = 0
                    else:
                        return
            self._play_from_source(kind, pid, next_idx, tracks[next_idx])
        elif kind == "playlist":
            pl = self.playlists.find(pid)
            if not pl:
                return
            tracks = pl["tracks"]
            if not tracks:
                return
            if self.shuffle:
                next_idx = self._next_shuffle_idx(len(tracks))
                if next_idx is None:
                    return
            else:
                next_idx = self.current_track_idx + (1 if forward else -1)
                if next_idx < 0:
                    next_idx = len(tracks) - 1
                elif next_idx >= len(tracks):
                    if self.repeat == "all" and from_end:
                        next_idx = 0
                    else:
                        return
            self._play_from_source(kind, pid, next_idx, tracks[next_idx])

    def _next_shuffle_idx(self, total):
        if not self.shuffle_order or len(self.shuffle_order) != total:
            self._generate_shuffle_order(total)
        self.shuffle_pos += 1
        if self.shuffle_pos >= len(self.shuffle_order):
            if self.repeat == "all":
                self._generate_shuffle_order(total)
                self.shuffle_pos = 0
            else:
                return None
        return self.shuffle_order[self.shuffle_pos]

    def _generate_shuffle_order(self, total):
        self.shuffle_order = list(range(total))
        random.shuffle(self.shuffle_order)
        self.shuffle_pos = 0

    def _play_from_source(self, kind, pid, idx, item):
        self.current_source = (kind, pid)
        self.current_track_idx = idx
        self.selections["queue" if kind == "queue" else "playlist"] = idx
        self._play_item(item)
        self._retry_count = 0

    def _animate(self):
        self._phase += 0.15
        if self.audio.paused or self.audio._stage != "streaming":
            for i in range(len(self.visualizer)):
                self.visualizer[i] *= 0.85
        else:
            for i in range(len(self.visualizer)):
                w1 = math.sin(self._phase * 0.8 + i * 0.55) * 0.35
                w2 = math.sin(self._phase * 1.7 + i * 0.31) * 0.25
                w3 = math.sin(self._phase * 3.1 + i * 0.83) * 0.15
                noise = (random.random() - 0.5) * 0.12
                v = 0.45 + w1 + w2 + w3 + noise
                dist = abs(i - len(self.visualizer) / 2) / (len(self.visualizer) / 2)
                v *= (1.0 - dist * 0.3)
                self.visualizer[i] = max(0.0, min(1.0, v))

    # ---------------- DRAW ----------------
    def draw(self):
        try:
            self.stdscr.erase()
            h, w = self.stdscr.getmaxyx()
            if h < 22 or w < 60:
                self.stdscr.addstr(0, 0, " terminal too small — minimum 60x22 ")
                self.stdscr.refresh()
                return
            self._draw_header(w)
            self._draw_tabs(w, 3)

            list_y, list_h = 5, h - 17
            if self.mode == "home":
                self._draw_home(list_y, list_h, w)
            elif self.mode == "search":
                self._draw_search_list(list_y, list_h, w)
            elif self.mode == "playlist":
                self._draw_playlist_split(list_y, list_h, w)
            elif self.mode == "queue":
                self._draw_queue(list_y, list_h, w)
            elif self.mode == "settings":
                self._draw_settings(list_y, list_h, w)

            self._draw_player(h, w)
            self._draw_search_bar(h - 4, w)
            self._draw_footer(h, w)

            if self.message and time.time() - self._msg_time < 3.0:
                try:
                    self.stdscr.addstr(h - 3, 2, truncate(self.message, w - 4),
                                       self._c(5, curses.A_BOLD))
                except curses.error:
                    pass
            elif self.message and time.time() - self._msg_time >= 3.0:
                self.message = ""
            self.stdscr.refresh()
        except curses.error:
            pass

    def _hline(self, y, w, ch="─", attr=0):
        try:
            self.stdscr.addstr(y, 0, ch * w, attr)
        except curses.error:
            pass

    def _hline_partial(self, y, x, width, ch, attr):
        if width <= 0:
            return
        try:
            self.stdscr.addstr(y, x, ch * width, attr)
        except curses.error:
            pass

    def _draw_header(self, w):
        try:
            self.stdscr.addstr(0, 1, self.S_MARK, self._c(1, curses.A_BOLD))
            self.stdscr.addstr(0, 3, "MUSIC", self._c(1, curses.A_BOLD))
            self.stdscr.addstr(0, 8, "·", self._c(2, curses.A_DIM))
            self.stdscr.addstr(0, 10, "TERMINAL", self._c(2))
            self.stdscr.addstr(0, 19, "v3.0", self._c(2, curses.A_DIM))
            stage = self.audio._stage
            if self.audio.error:
                st, sc = "ERROR", 4
            elif stage in ("opening", "decoding"):
                st, sc = "LOADING", 3
            elif stage == "streaming" and not self.audio.paused:
                st, sc = "PLAYING", 1
            elif stage == "streaming" and self.audio.paused:
                st, sc = "PAUSED", 3
            else:
                st, sc = "ONLINE", 1
            label = f"{self.S_DOT} {st}"
            self.stdscr.addstr(0, w - len(label) - 2, label,
                               self._c(sc, curses.A_BOLD))
        except curses.error:
            pass
        self._hline(1, w, "─", self._c(2, curses.A_DIM))

    def _draw_tabs(self, w, y):
        tabs = [("home", "HOME"), ("search", "SEARCH"),
                ("playlist", "PLAYLIST"), ("queue", "QUEUE"), ("settings", "CONFIG")]
        x = 2
        for mode_key, label in tabs:
            active = (self.mode == mode_key)
            marker = self.S_MARK if active else self.S_CIRCLE
            attr = self._c(1, curses.A_BOLD) if active else self._c(2, curses.A_DIM)
            try:
                self.stdscr.addstr(y, x, marker, attr)
                self.stdscr.addstr(y, x + 2, label, attr)
            except curses.error:
                pass
            x += len(label) + 5

    def _draw_home(self, y0, h, w):
        if not self.home_sections:
            try:
                self.stdscr.addstr(y0 + 1, 4, "— loading home… —",
                                   self._c(2, curses.A_DIM))
                self.stdscr.addstr(y0 + 2, 4, f"{spinner_frame(self._phase)} fetching",
                                   self._c(3))
            except curses.error:
                pass
            return
        # flat list com separadores
        flat = []
        for title, items in self.home_sections:
            flat.append(("header", title))
            for it in items:
                flat.append(("track", it))
        sel = self.selections["home"]
        if sel >= len(flat):
            sel = max(0, len(flat) - 1)
            self.selections["home"] = sel
        # contam só tracks pra mapear seleção "útil"
        track_positions = [i for i, x in enumerate(flat) if x[0] == "track"]
        # desloca a lista pra garantir que a seleção esteja visível
        visible = min(len(flat), h)
        if sel < visible:
            start = 0
        else:
            start = sel - visible + 1
        # mas start deve ser um header para não cortar seção no meio
        for i in range(start - 1, -1, -1):
            if flat[i][0] == "header":
                start = i
                break

        for j in range(start, min(start + visible, len(flat))):
            kind, data = flat[j]
            row_y = y0 + (j - start)
            try:
                if kind == "header":
                    self.stdscr.addstr(row_y, 2, self.S_MARK,
                                       self._c(2, curses.A_BOLD))
                    self.stdscr.addstr(row_y, 4, truncate(data, w - 8),
                                       self._c(2, curses.A_BOLD | curses.A_DIM))
                else:
                    is_sel = (j == sel)
                    is_playing = (data.get("url") == self.current_url and self.current_url)
                    marker = self.S_MARK if is_sel else (self.S_NOTE if is_playing else " ")
                    dur = data.get("duration", "")
                    dur_w = 7 if dur else 0
                    title_w = max(10, w - 12 - dur_w)
                    if is_sel:
                        attr = self._c(1, curses.A_BOLD)
                    elif is_playing:
                        attr = self._c(2)
                    else:
                        attr = self._c(5)
                    self.stdscr.addstr(row_y, 4, marker, attr)
                    self.stdscr.addstr(row_y, 6, truncate(data.get("title", "?"), title_w).ljust(title_w), attr)
                    if dur:
                        self.stdscr.addstr(row_y, w - dur_w - 2, dur,
                                           self._c(2, curses.A_DIM))
            except curses.error:
                pass

    def _draw_search_list(self, y0, h, w):
        if self.search_loading:
            try:
                self.stdscr.addstr(y0 + 1, 4, "— searching… —",
                                   self._c(3))
                self.stdscr.addstr(y0 + 2, 4,
                                   f"{spinner_frame(self._phase)} {self.search_query[:40]}",
                                   self._c(2, curses.A_DIM))
            except curses.error:
                pass
            return
        visible_items = self.search_all_cache[:self.search_shown]
        if not visible_items:
            try:
                self.stdscr.addstr(y0 + 1, 4, "— no results —",
                                   self._c(2, curses.A_DIM))
                self.stdscr.addstr(y0 + 2, 4, "press / to search",
                                   self._c(2, curses.A_DIM))
            except curses.error:
                pass
            return
        sel = self.selections["search"]
        if sel >= len(visible_items):
            sel = len(visible_items) - 1
            self.selections["search"] = sel
        visible = min(len(visible_items), h)
        start = max(0, sel - visible + 1) if sel >= visible else 0
        for i in range(start, min(start + visible, len(visible_items))):
            item = visible_items[i]
            is_sel = (i == sel)
            is_playing = (item.get("url") == self.current_url and self.current_url)
            marker = self.S_MARK if is_sel else (self.S_NOTE if is_playing else " ")
            dur = item.get("duration", "")
            dur_w = 7 if dur else 0
            title_w = max(10, w - 12 - dur_w)
            if is_sel:
                attr = self._c(1, curses.A_BOLD)
            elif is_playing:
                attr = self._c(2)
            else:
                attr = self._c(5)
            try:
                self.stdscr.addstr(y0 + (i - start), 2, marker, attr)
                self.stdscr.addstr(y0 + (i - start), 4, f"{i+1:02d}",
                                   self._c(2, curses.A_DIM))
                self.stdscr.addstr(y0 + (i - start), 8,
                                   truncate(item.get("title", "?"), title_w).ljust(title_w), attr)
                if dur:
                    self.stdscr.addstr(y0 + (i - start), w - dur_w - 2, dur,
                                       self._c(2, curses.A_DIM))
            except curses.error:
                pass
        if self.search_more_loading:
            try:
                self.stdscr.addstr(y0 + min(len(visible_items) - start, h - 1),
                                   w - 16,
                                   f"{spinner_frame(self._phase)} load more",
                                   self._c(3, curses.A_DIM))
            except curses.error:
                pass
        elif self.search_shown >= len(self.search_all_cache) and len(self.search_all_cache) > 0:
            try:
                self.stdscr.addstr(y0 + min(len(visible_items) - start, h - 1),
                                   w - 16, "— end —",
                                   self._c(2, curses.A_DIM))
            except curses.error:
                pass

    def _draw_playlist_split(self, y0, h, w):
        left_w = min(30, max(20, w // 3))
        sep_x = left_w
        right_x = left_w + 2
        right_w = max(10, w - right_x - 2)
        for yy in range(y0, y0 + h):
            try:
                self.stdscr.addstr(yy, sep_x, "│", self._c(2, curses.A_DIM))
            except curses.error:
                pass
        try:
            self.stdscr.addstr(y0, 2, "PLAYLISTS",
                               self._c(2, curses.A_BOLD | curses.A_DIM))
            self.stdscr.addstr(y0, right_x, "TRACKS",
                               self._c(2, curses.A_BOLD | curses.A_DIM))
        except curses.error:
            pass
        self._hline_partial(y0 + 1, 2, left_w - 3, "─", self._c(2, curses.A_DIM))
        self._hline_partial(y0 + 1, right_x, right_w, "─", self._c(2, curses.A_DIM))

        playlists = self.playlists.get_all()
        focus_list = (self.playlist_focus == "list")
        total_rows = min(len(playlists) + 1, h - 2)
        for i in range(total_rows):
            row_y = y0 + 3 + i
            is_sel = (i == self.playlist_cursor)
            if i == len(playlists):
                marker = self.S_MARK if is_sel and focus_list else " "
                attr = (self._c(3, curses.A_BOLD) if is_sel and focus_list
                        else self._c(2, curses.A_DIM))
                try:
                    self.stdscr.addstr(row_y, 2, marker, attr)
                    self.stdscr.addstr(row_y, 4, truncate("+ new playlist", left_w - 6), attr)
                except curses.error:
                    pass
                continue
            pl = playlists[i]
            is_active = (pl["id"] == self.playlists.active_id)
            note = self.S_NOTE if is_active else " "
            marker = self.S_MARK if is_sel and focus_list else " "
            text = f"{note} {pl['name']}"
            if is_sel and focus_list:
                attr = self._c(1, curses.A_BOLD)
            elif is_active:
                attr = self._c(1)
            else:
                attr = self._c(5)
            try:
                self.stdscr.addstr(row_y, 2, marker, attr)
                self.stdscr.addstr(row_y, 4, truncate(text, left_w - 6), attr)
            except curses.error:
                pass

        sel_pl = self._get_cursor_playlist()
        if sel_pl is None:
            try:
                self.stdscr.addstr(y0 + 3, right_x, "(no playlist)",
                                   self._c(2, curses.A_DIM))
            except curses.error:
                pass
            return
        tracks = sel_pl["tracks"]
        if not tracks:
            try:
                self.stdscr.addstr(y0 + 3, right_x, "— empty playlist —",
                                   self._c(2, curses.A_DIM))
                self.stdscr.addstr(y0 + 4, right_x, "play something and press A",
                                   self._c(2, curses.A_DIM))
            except curses.error:
                pass
            return
        focus_tracks = (self.playlist_focus == "tracks")
        visible = min(len(tracks), h - 2)
        tc = self.track_cursor
        start = max(0, tc - visible + 1) if tc >= visible else 0
        for i in range(start, min(start + visible, len(tracks))):
            tr = tracks[i]
            row_y = y0 + 3 + (i - start)
            is_sel = (i == tc)
            is_playing = (tr.get("url") == self.current_url and self.current_url)
            marker = (self.S_MARK if is_sel and focus_tracks
                      else self.S_NOTE if is_playing else " ")
            num = f"{i+1:02d}"
            title = tr.get("title", "?")
            dur = tr.get("duration", "")
            dur_w = len(dur) + 1 if dur else 0
            title_w = right_w - 8 - dur_w
            if is_sel and focus_tracks:
                attr, num_attr = self._c(1, curses.A_BOLD), self._c(1, curses.A_DIM)
            elif is_playing:
                attr, num_attr = self._c(2), self._c(2, curses.A_DIM)
            else:
                attr, num_attr = self._c(5), self._c(2, curses.A_DIM)
            try:
                self.stdscr.addstr(row_y, right_x, marker, attr)
                self.stdscr.addstr(row_y, right_x + 2, num, num_attr)
                self.stdscr.addstr(row_y, right_x + 5,
                                   truncate(title, title_w).ljust(title_w), attr)
                if dur:
                    self.stdscr.addstr(row_y, w - dur_w - 2, dur,
                                       self._c(2, curses.A_DIM))
            except curses.error:
                pass

    def _draw_queue(self, y0, h, w):
        tracks = self.queue.tracks
        try:
            self.stdscr.addstr(y0, 2, "TEMPORARY QUEUE",
                               self._c(2, curses.A_BOLD | curses.A_DIM))
        except curses.error:
            pass
        self._hline_partial(y0 + 1, 2, w - 4, "─", self._c(2, curses.A_DIM))
        if not tracks:
            try:
                self.stdscr.addstr(y0 + 3, 4, "— queue is empty —",
                                   self._c(2, curses.A_DIM))
                self.stdscr.addstr(y0 + 4, 4, "press F on any track to queue it",
                                   self._c(2, curses.A_DIM))
            except curses.error:
                pass
            return
        sel = self.selections["queue"]
        if sel >= len(tracks):
            sel = len(tracks) - 1
            self.selections["queue"] = sel
        visible = min(len(tracks), h - 2)
        start = max(0, sel - visible + 1) if sel >= visible else 0
        for i in range(start, min(start + visible, len(tracks))):
            tr = tracks[i]
            row_y = y0 + 3 + (i - start)
            is_sel = (i == sel)
            is_playing = (tr.get("url") == self.current_url and self.current_url)
            marker = self.S_MARK if is_sel else (self.S_NOTE if is_playing else " ")
            dur = tr.get("duration", "")
            dur_w = 7 if dur else 0
            title_w = max(10, w - 12 - dur_w)
            if is_sel:
                attr = self._c(1, curses.A_BOLD)
            elif is_playing:
                attr = self._c(2)
            else:
                attr = self._c(5)
            try:
                self.stdscr.addstr(row_y, 2, marker, attr)
                self.stdscr.addstr(row_y, 4, f"{i+1:02d}",
                                   self._c(2, curses.A_DIM))
                self.stdscr.addstr(row_y, 8,
                                   truncate(tr.get("title", "?"), title_w).ljust(title_w), attr)
                if dur:
                    self.stdscr.addstr(row_y, w - dur_w - 2, dur,
                                       self._c(2, curses.A_DIM))
            except curses.error:
                pass

    def _draw_settings(self, y0, h, w):
        try:
            self.stdscr.addstr(y0, 2, "APPEARANCE",
                               self._c(2, curses.A_BOLD | curses.A_DIM))
        except curses.error:
            pass
        self._hline_partial(y0 + 1, 2, 20, "─", self._c(2, curses.A_DIM))
        for i, slot in enumerate(Theme.SLOTS):
            y = y0 + 3 + i
            is_sel = (i == self.settings_cursor)
            current = self.config.get("appearance", slot, default="default")
            marker = self.S_MARK if is_sel else " "
            try:
                self.stdscr.addstr(y, 2, marker,
                                   self._c(1, curses.A_BOLD) if is_sel else 0)
                self.stdscr.addstr(y, 4, slot.ljust(11),
                                   self._c(1, curses.A_BOLD) if is_sel else self._c(2))
                self.stdscr.addstr(y, 17, str(current),
                                   self._c(i + 1, curses.A_BOLD))
            except curses.error:
                pass
        info_y = y0 + 3 + len(Theme.SLOTS) + 1
        try:
            self.stdscr.addstr(info_y, 2, "← → cycle color", self._c(2, curses.A_DIM))
            self.stdscr.addstr(info_y + 1, 2,
                               f"config: {os.path.basename(self.config.path)}",
                               self._c(2, curses.A_DIM))
            self.stdscr.addstr(info_y + 2, 2,
                               "edit file for RGB [R,G,B] values",
                               self._c(2, curses.A_DIM))
        except curses.error:
            pass

    def _draw_player(self, h, w):
        self._hline(h - 11, w, "═", self._c(2, curses.A_DIM))
        try:
            self.stdscr.addstr(h - 10, 2, self.S_NOTE, self._c(1, curses.A_BOLD))
        except curses.error:
            pass
        stage = self.audio._stage
        if self.audio.error:
            title, t_attr = f"erro: {self.audio.error}", self._c(4, curses.A_BOLD)
        elif stage == "opening":
            title, t_attr = "abrindo stream...", self._c(3)
        elif stage == "decoding":
            title, t_attr = "decodificando...", self._c(3)
        elif stage == "done":
            title, t_attr = self.current_title + "  [end]", self._c(2, curses.A_DIM)
        elif self.current_url:
            title, t_attr = self.current_title, self._c(5, curses.A_BOLD)
        else:
            title, t_attr = "no track loaded", self._c(2, curses.A_DIM)
        try:
            self.stdscr.addstr(h - 10, 4, truncate(title, w - 8), t_attr)
        except curses.error:
            pass

        pos, dur = self.audio.time_pos, self.audio.duration
        bar_x, bar_w = 2, w - 4
        try:
            if dur > 0:
                ratio = min(1.0, max(0.0, pos / dur))
                filled = int(ratio * (bar_w - 1))
                self.stdscr.addstr(h - 9, bar_x, "━" * filled, self._c(1, curses.A_BOLD))
                self.stdscr.addstr(h - 9, bar_x + filled, self.S_DOT,
                                   self._c(1, curses.A_BOLD))
                rest = bar_w - filled - 1
                if rest > 0:
                    self.stdscr.addstr(h - 9, bar_x + filled + 1, "─" * rest,
                                       self._c(2, curses.A_DIM))
            else:
                self.stdscr.addstr(h - 9, bar_x, "─" * bar_w,
                                   self._c(2, curses.A_DIM))
        except curses.error:
            pass

        try:
            if self.audio.paused or not self.current_url:
                icon, icon_attr = self.S_PAUSE, self._c(3, curses.A_BOLD)
            else:
                icon, icon_attr = self.S_PLAY, self._c(1, curses.A_BOLD)
            self.stdscr.addstr(h - 8, 2, icon, icon_attr)
            time_str = f"{fmt_time(pos)}  ·  {fmt_time(dur) if dur else '--:--'}"
            self.stdscr.addstr(h - 8, 5, time_str, self._c(2, curses.A_DIM))

            # indicadores de modo (centro)
            mode_parts = []
            if self.shuffle:
                mode_parts.append("⇄ SHF")
            if self.repeat == "all":
                mode_parts.append("↻ ALL")
            elif self.repeat == "one":
                mode_parts.append("↻ 1")
            mode_str = "  ".join(mode_parts)
            if mode_str:
                mx = max(5 + len(time_str) + 3, (w - len(mode_str)) // 2)
                self.stdscr.addstr(h - 8, mx, mode_str, self._c(1, curses.A_BOLD))

            vol_str = f"VOL {int(self.audio.volume*100):3d}%"
            self.stdscr.addstr(h - 8, w - len(vol_str) - 2, vol_str,
                               self._c(2, curses.A_DIM))
        except curses.error:
            pass

        try:
            n_bars = min(len(self.visualizer), max(10, w - 16))
            for i in range(n_bars):
                v = self.visualizer[i]
                idx = int(v * (len(self.VIZ) - 1))
                ch = self.VIZ[idx]
                if v < 0.1:
                    attr = self._c(2, curses.A_DIM)
                elif v > 0.65:
                    attr = self._c(1, curses.A_BOLD)
                else:
                    attr = self._c(1)
                self.stdscr.addstr(h - 7, 2 + i, ch, attr)
        except curses.error:
            pass
        self._hline(h - 6, w, "═", self._c(2, curses.A_DIM))

    def _draw_search_bar(self, y, w):
        try:
            icon_attr = (self._c(3, curses.A_BOLD) if self.input_mode
                         else self._c(2, curses.A_DIM))
            self.stdscr.addstr(y, 2, self.S_SEARCH, icon_attr)
            if self.input_mode:
                text = self.input_buffer
                avail = w - 8
                shown = text[-avail:] if len(text) > avail else text
                self.stdscr.addstr(y, 4, shown, self._c(5))
                cx = 4 + len(shown)
                if cx < w - 1:
                    self.stdscr.addstr(y, cx, " ", curses.A_REVERSE)
            elif self.search_loading:
                self.stdscr.addstr(y, 4,
                                   f"{spinner_frame(self._phase)} searching {self.search_query[:40]}",
                                   self._c(3))
            else:
                if self.search_query:
                    self.stdscr.addstr(y, 4, truncate(self.search_query, w - 8),
                                       self._c(2))
                else:
                    self.stdscr.addstr(y, 4, "press / to search",
                                       self._c(2, curses.A_DIM))
        except curses.error:
            pass

    def _draw_footer(self, h, w):
        self._hline(h - 2, w, "─", self._c(2, curses.A_DIM))
        if self.input_mode:
            keys = [("ENTER", "confirm"), ("ESC", "cancel")]
        elif self.mode == "queue":
            keys = [("↑↓", "nav"), ("ENTER", "play"), ("F", "add"),
                    ("D", "del"), ("J/K", "move"), ("L", "clear"),
                    ("TAB", "tab"), ("Q", "quit")]
        elif self.mode == "playlist":
            if self.playlist_focus == "list":
                keys = [("↑↓", "nav"), ("ENTER", "open"), ("N", "new"),
                        ("R", "rename"), ("X", "del"), ("A", "add"),
                        ("L", "active"), ("TAB", "tab"), ("Q", "quit")]
            else:
                keys = [("↑↓", "nav"), ("ENTER", "play"), ("D", "del"),
                        ("U/J", "move"), ("F", "queue"), ("BS", "back")]
        elif self.mode == "settings":
            keys = [("↑↓", "nav"), ("←→", "cycle"), ("Q", "quit")]
        else:
            keys = [("SPACE", "play"), ("←→", "seek"), ("↑↓", "nav"),
                    ("F", "queue"), ("S", "shuffle"), ("R", "repeat"),
                    ("TAB", "tab"), ("/", "search"), ("A", "add"),
                    ("Q", "quit")]
        x = 1
        for k, label in keys:
            try:
                self.stdscr.addstr(h - 1, x, k, self._c(1, curses.A_DIM))
                x += len(k) + 1
                self.stdscr.addstr(h - 1, x, label, self._c(2, curses.A_DIM))
                x += len(label) + 2
            except curses.error:
                break

    # ---------------- helpers ----------------
    def _current_items(self):
        if self.mode == "home":
            return self._home_flat_items()
        if self.mode == "search":
            return self.search_all_cache[:self.search_shown]
        if self.mode == "queue":
            return self.queue.tracks
        return []

    def _get_cursor_playlist(self):
        playlists = self.playlists.get_all()
        if 0 <= self.playlist_cursor < len(playlists):
            return playlists[self.playlist_cursor]
        return None

    # ---------------- INPUT ----------------
    def handle_key(self, key):
        if self.input_mode:
            self._handle_input_key(key)
            return
        if key == ord("q"):
            self.running = False
            return
        if key == 27:
            if self.mode == "playlist" and self.playlist_focus == "tracks":
                self.playlist_focus = "list"
            else:
                self.running = False
            return
        if key == ord(" "):
            self.audio.toggle_pause()
            return
        if key == curses.KEY_RIGHT:
            self.audio.seek(10)
            return
        if key == curses.KEY_LEFT:
            self.audio.seek(-10)
            return
        if key in (ord("-"), ord("_")):
            self.audio.set_volume(round(self.audio.volume * 100) - 5)
            return
        if key in (ord("+"), ord("=")):
            self.audio.set_volume(round(self.audio.volume * 100) + 5)
            return
        if key == ord("\t"):
            cyc = ["home", "search", "playlist", "queue", "settings"]
            self.mode = cyc[(cyc.index(self.mode) + 1) % len(cyc)]
            return
        if key == ord("/"):
            self._prompt_search()
            return
        if key == ord("s"):
            self.shuffle = not self.shuffle
            if self.shuffle and self.current_source:
                kind, _ = self.current_source
                n = len(self._source_tracks(kind))
                self._generate_shuffle_order(n)
                if self.current_track_idx in self.shuffle_order:
                    self.shuffle_pos = self.shuffle_order.index(self.current_track_idx)
            self.message = f"shuffle: {'on' if self.shuffle else 'off'}"
            self._msg_time = time.time()
            return
        if key == ord("r"):
            self.repeat = {"off": "all", "all": "one", "one": "off"}[self.repeat]
            self.message = f"repeat: {self.repeat}"
            self._msg_time = time.time()
            return
        if key == ord("f"):
            self._add_cursor_to_queue()
            return
        if self.mode == "home":
            self._handle_home_key(key)
        elif self.mode == "search":
            self._handle_search_key(key)
        elif self.mode == "playlist":
            self._handle_playlist_key(key)
        elif self.mode == "queue":
            self._handle_queue_key(key)
        elif self.mode == "settings":
            self._handle_settings_key(key)

    def _source_tracks(self, kind):
        if kind == "queue":
            return self.queue.tracks
        if kind == "playlist" and self.current_source:
            pl = self.playlists.find(self.current_source[1])
            if pl:
                return pl["tracks"]
        return []

    def _prompt_search(self):
        self.input_mode = True
        self.input_buffer = ""
        self._input_purpose = "search"

    def _handle_input_key(self, key):
        if key == 27:
            self.input_mode = False
            self.input_buffer = ""
            self._input_purpose = "search"
            return
        if key in (curses.KEY_ENTER, 10, 13):
            purpose = self._input_purpose
            text = self.input_buffer.strip()
            self.input_mode = False
            self.input_buffer = ""
            self._input_purpose = "search"
            if purpose == "search":
                self.search_query = text
                if text:
                    self._do_search(text)
            elif purpose == "new_playlist":
                if text:
                    p = self.playlists.create_playlist(text)
                    self.playlist_cursor = len(self.playlists.get_all()) - 1
                    self.message = f"created: {p['name']}"
                    self._msg_time = time.time()
            elif purpose == "rename_playlist" and self._rename_target:
                if text:
                    self.playlists.rename_playlist(self._rename_target, text)
                    self.message = f"renamed to: {text}"
                    self._msg_time = time.time()
                self._rename_target = None
            return
        if key in (curses.KEY_BACKSPACE, 8, 127):
            self.input_buffer = self.input_buffer[:-1]
            return
        try:
            c = chr(key)
            if c.isprintable():
                self.input_buffer += c
        except Exception:
            pass

    def _handle_home_key(self, key):
        # navegação sobre a lista flat (headers pulados)
        flat = []
        for title, items in self.home_sections:
            flat.append(("header", None))
            for it in items:
                flat.append(("track", it))
        track_idxs = [i for i, x in enumerate(flat) if x[0] == "track"]
        if not track_idxs:
            return
        sel = self.selections["home"]
        # ajusta sel para um track válido
        if sel not in track_idxs:
            sel = track_idxs[0]
            self.selections["home"] = sel
        if key == curses.KEY_UP:
            pos = track_idxs.index(sel)
            if pos > 0:
                self.selections["home"] = track_idxs[pos - 1]
        elif key == curses.KEY_DOWN:
            pos = track_idxs.index(sel)
            if pos < len(track_idxs) - 1:
                self.selections["home"] = track_idxs[pos + 1]
        elif key in (curses.KEY_ENTER, 10, 13):
            item = flat[sel][1]
            if item:
                self.current_source = None
                self._play_item(item)
        elif key == ord("a"):
            item = flat[sel][1]
            if item:
                self._add_track_to_active(item)

    def _handle_search_key(self, key):
        items = self._current_items()
        if key == curses.KEY_UP:
            self.selections["search"] = max(0, self.selections["search"] - 1)
        elif key == curses.KEY_DOWN:
            if items:
                self.selections["search"] = min(len(items) - 1,
                                                 self.selections["search"] + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if 0 <= self.selections["search"] < len(items):
                self.current_source = None
                self._play_item(items[self.selections["search"]])
        elif key == ord("a"):
            if 0 <= self.selections["search"] < len(items):
                self._add_track_to_active(items[self.selections["search"]])

    def _handle_playlist_key(self, key):
        if self.playlist_focus == "list":
            self._handle_playlist_list_key(key)
        else:
            self._handle_playlist_tracks_key(key)

    def _handle_playlist_list_key(self, key):
        playlists = self.playlists.get_all()
        total = len(playlists) + 1
        if key == curses.KEY_UP:
            self.playlist_cursor = max(0, self.playlist_cursor - 1)
        elif key == curses.KEY_DOWN:
            self.playlist_cursor = min(total - 1, self.playlist_cursor + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.playlist_cursor == len(playlists):
                self._prompt_new_playlist()
            else:
                self.playlist_focus = "tracks"
                self.track_cursor = 0
        elif key == ord("n"):
            self._prompt_new_playlist()
        elif key == ord("r"):
            if self.playlist_cursor < len(playlists):
                self._prompt_rename_playlist(playlists[self.playlist_cursor])
        elif key == ord("x"):
            if self.playlist_cursor < len(playlists):
                pl = playlists[self.playlist_cursor]
                self.playlists.delete_playlist(pl["id"])
                self.playlist_cursor = min(self.playlist_cursor,
                                           max(0, len(self.playlists.get_all()) - 1))
                self.message = f"deleted: {pl['name']}"
                self._msg_time = time.time()
        elif key == ord("a"):
            self._add_current_to_cursor_playlist()
        elif key == ord("l"):
            if self.playlist_cursor < len(playlists):
                pl = playlists[self.playlist_cursor]
                self.playlists.set_active(pl["id"])
                self.message = f"active: {pl['name']}"
                self._msg_time = time.time()

    def _handle_playlist_tracks_key(self, key):
        pl = self._get_cursor_playlist()
        if not pl:
            self.playlist_focus = "list"
            return
        tracks = pl["tracks"]
        if key in (curses.KEY_BACKSPACE, 8, 127):
            self.playlist_focus = "list"
            return
        if key == curses.KEY_UP:
            self.track_cursor = max(0, self.track_cursor - 1)
        elif key == curses.KEY_DOWN:
            if tracks:
                self.track_cursor = min(len(tracks) - 1, self.track_cursor + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if 0 <= self.track_cursor < len(tracks):
                self.playlists.set_active(pl["id"])
                self._play_from_source("playlist", pl["id"], self.track_cursor,
                                       tracks[self.track_cursor])
        elif key == ord("d"):
            if 0 <= self.track_cursor < len(tracks):
                tr = tracks[self.track_cursor]
                self.playlists.remove_track(pl["id"], self.track_cursor)
                self.track_cursor = min(self.track_cursor,
                                        max(0, len(pl["tracks"]) - 1))
                self.message = f"removed: {tr.get('title', '?')[:30]}"
                self._msg_time = time.time()
        elif key == ord("u"):
            if self.track_cursor > 0:
                self.playlists.move_track(pl["id"], self.track_cursor, -1)
                self.track_cursor -= 1
        elif key == ord("j"):
            if self.track_cursor < len(tracks) - 1:
                self.playlists.move_track(pl["id"], self.track_cursor, 1)
                self.track_cursor += 1
        elif key == ord("f"):
            if 0 <= self.track_cursor < len(tracks):
                if self.queue.add(tracks[self.track_cursor]):
                    self.message = "added to queue"
                else:
                    self.message = "already in queue"
                self._msg_time = time.time()

    def _handle_queue_key(self, key):
        tracks = self.queue.tracks
        sel = self.selections["queue"]
        if key == curses.KEY_UP:
            self.selections["queue"] = max(0, sel - 1)
        elif key == curses.KEY_DOWN:
            if tracks:
                self.selections["queue"] = min(len(tracks) - 1, sel + 1)
        elif key in (curses.KEY_ENTER, 10, 13):
            if 0 <= sel < len(tracks):
                self._play_from_source("queue", None, sel, tracks[sel])
        elif key == ord("d"):
            if 0 <= sel < len(tracks):
                tr = self.queue.remove(sel)
                self.selections["queue"] = min(sel, max(0, len(self.queue.tracks) - 1))
                if tr:
                    self.message = f"removed: {tr.get('title', '?')[:30]}"
                    self._msg_time = time.time()
        elif key == ord("j"):
            if self.queue.move(sel, 1):
                self.selections["queue"] = sel + 1
        elif key == ord("k"):
            if self.queue.move(sel, -1):
                self.selections["queue"] = sel - 1
        elif key == ord("l"):
            self.queue.clear()
            self.selections["queue"] = 0
            self.message = "queue cleared"
            self._msg_time = time.time()

    def _handle_settings_key(self, key):
        n = len(Theme.SLOTS)
        if key == curses.KEY_UP:
            self.settings_cursor = max(0, self.settings_cursor - 1)
        elif key == curses.KEY_DOWN:
            self.settings_cursor = min(n - 1, self.settings_cursor + 1)
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT,
                     curses.KEY_ENTER, 10, 13):
            slot = Theme.SLOTS[self.settings_cursor]
            new = self.theme.cycle(slot)
            self.message = f"{slot} = {new}"
            self._msg_time = time.time()

    # ---------------- actions ----------------
    def _do_search(self, query):
        self.search_loading = True
        self.search_all_cache = []
        self.search_shown = 0
        self.search_results = []
        self.selections["search"] = 0
        self.mode = "search"
        self._search_req_id += 1
        my_id = self._search_req_id

        def worker():
            results = self.youtube.search_initial(query, total=50)
            if my_id != self._search_req_id:
                return
            self.search_all_cache = results
            self.search_shown = min(15, len(results))
            self.search_loading = False

        threading.Thread(target=worker, daemon=True).start()

    def _reveal_more(self):
        if self.search_more_loading:
            return
        if self.search_shown >= len(self.search_all_cache):
            return
        self.search_more_loading = True
        target_shown = min(self.search_shown + 15, len(self.search_all_cache))
        time.sleep(0.05)
        self.search_shown = target_shown
        self.search_more_loading = False

    def _play_item(self, item):
        url = item.get("url")
        if not url:
            return
        self.current_title = "loading…"
        self.audio.error = None
        audio_url, title, duration = self.youtube.get_audio_info(url)
        if not audio_url:
            self.message = ("live streams not supported" if title == "LIVE"
                            else "could not resolve audio url")
            self._msg_time = time.time()
            self.audio.error = "no url"
            return
        if duration:
            item["duration"] = fmt_time(duration)
        self.audio.load(audio_url)
        self.audio.play()
        self.current_title = title or item.get("title", "?")
        self.current_url = url
        self._retry_count = 0
        try:
            self.playlists.add_history({
                "title": self.current_title,
                "url": url,
                "duration": item.get("duration", ""),
            }, limit=self.config.get("behavior", "history_limit", default=50))
        except Exception:
            pass

    def _next_track(self):
        self._advance_track(forward=True, from_end=False)

    def _prev_track(self):
        self._advance_track(forward=False, from_end=False)

    def _add_track_to_active(self, item):
        pl = self.playlists.get_active()
        if not pl:
            return
        track = {
            "title": item.get("title", "?"),
            "url": item.get("url"),
            "duration": item.get("duration", ""),
        }
        if self.playlists.add_track(pl["id"], track):
            self.message = f"added to {pl['name']}"
        else:
            self.message = "already in playlist"
        self._msg_time = time.time()

    def _add_current_to_cursor_playlist(self):
        if not self.current_url:
            return
        pl = self._get_cursor_playlist()
        if not pl:
            return
        track = {
            "title": self.current_title,
            "url": self.current_url,
            "duration": fmt_time(self.audio.duration) if self.audio.duration else "",
        }
        if self.playlists.add_track(pl["id"], track):
            self.message = f"added to {pl['name']}"
        else:
            self.message = "already in playlist"
        self._msg_time = time.time()

    def _add_cursor_to_queue(self):
        item = None
        if self.mode == "home":
            flat = []
            for title, items in self.home_sections:
                flat.append(("header", None))
                for it in items:
                    flat.append(("track", it))
            sel = self.selections["home"]
            if 0 <= sel < len(flat) and flat[sel][0] == "track":
                item = flat[sel][1]
        elif self.mode == "search":
            items = self.search_all_cache[:self.search_shown]
            sel = self.selections["search"]
            if 0 <= sel < len(items):
                item = items[sel]
        elif self.mode == "playlist" and self.playlist_focus == "tracks":
            pl = self._get_cursor_playlist()
            if pl and 0 <= self.track_cursor < len(pl["tracks"]):
                item = pl["tracks"][self.track_cursor]
        elif self.mode == "queue":
            if 0 <= self.selections["queue"] < len(self.queue.tracks):
                item = self.queue.tracks[self.selections["queue"]]
        if not item:
            return
        if self.queue.add(item):
            self.message = "added to queue"
        else:
            self.message = "already in queue"
        self._msg_time = time.time()

    def _prompt_new_playlist(self):
        self.input_mode = True
        self.input_buffer = ""
        self._input_purpose = "new_playlist"

    def _prompt_rename_playlist(self, pl):
        self.input_mode = True
        self.input_buffer = pl["name"]
        self._input_purpose = "rename_playlist"
        self._rename_target = pl["id"]


def main(stdscr):
    app = PlayerApp(stdscr)
    try:
        app.run()
    finally:
        app.audio.close()
        log("=== FIM ===")


if __name__ == "__main__":
    ok = test_audio_device()
    if not ok:
        print("\naudio device test failed — check Windows sound settings.\n")
        input("press ENTER to continue anyway…")
    try:
        curses.wrapper(main)
    except KeyboardInterrupt:
        pass
    except Exception:
        log(f"CRASH:\n{traceback.format_exc()}")
        raise