"""Aplicação principal: loop de eventos, atalhos globais e ciclo de vida."""
import curses
import os
import sys
import time
import traceback

from . import __version__, memory
from .audio.player import BANDS, AudioPlayer
from .config import ConfigManager
from .logger import log, reset_log
from .paths import ensure_dirs, migrate_legacy
from .playback import PlaybackController
from .services.home_feed import HomeFeed
from .services.youtube import YouTubeService
from .storage.playlists import PlaylistManager
from .storage.queue import QueueManager
from .theme import Theme
from .ui import chrome
from .ui.home import HomeScreen
from .ui.playlists import PlaylistsScreen
from .ui.queue import QueueScreen
from .ui.search import SearchScreen
from .ui.settings import SettingsScreen
from .ui.widgets import put

MIN_H, MIN_W = 22, 60


class PlayerApp:
    S_MARK = "▸"
    S_DOT = "●"
    S_CIRCLE = "○"
    S_NOTE = "♫"
    S_PLAY = "▶"
    S_PAUSE = "❚❚"
    S_SEARCH = "⌕"
    VIZ = " ▁▂▃▄▅▆▇█"

    def __init__(self, stdscr):
        self.stdscr = stdscr
        self.config = ConfigManager()
        self.theme = Theme(self.config)
        self.playlists = PlaylistManager()
        self.queue = QueueManager()
        self.audio = AudioPlayer()
        self.youtube = YouTubeService()
        self.home = HomeFeed(self.youtube, self.playlists, self.config)
        self.playback = PlaybackController(self)

        self.screens = {
            "home": HomeScreen(self),
            "search": SearchScreen(self),
            "playlist": PlaylistsScreen(self),
            "queue": QueueScreen(self),
            "settings": SettingsScreen(self),
        }
        self.mode = "home"
        self.running = True
        self.viz = [0.0] * BANDS
        self.viz_on = True
        self._t0 = time.time()

        self.message = ""
        self.msg_time = 0.0
        self.show_help = False

        # campo de texto (busca, nome de playlist…)
        self.input_mode = False
        self.input_buffer = ""
        self.input_label = "search"
        self._input_cb = None
        self._search_history = []
        self._hist_pos = None

        self._mem_label = ""
        self._mem_time = 0.0
        self.trim_on = True
        self._trim_t = time.time()
        self._trim_gen = -1

        self._restore_preferences()
        self.apply_config()
        self.home.start()

    # ------------------------------------------------------------ utilidades
    @property
    def phase(self):
        return time.time() - self._t0

    def c(self, n, extra=0):
        return self.theme.pair(n) | extra

    def notify(self, text):
        self.message = text
        self.msg_time = time.time()

    def set_mode(self, mode):
        if mode in self.screens:
            self.mode = mode
            self.screens[mode].on_enter()

    def add_to_active(self, item):
        pl = self.playlists.get_active()
        if not pl or not item:
            return
        ok = self.playlists.add_track(pl["id"], item)
        self.home.invalidate()
        self.notify(f"added to {pl['name']}" if ok else "already in playlist")

    def prompt(self, label, callback, initial=""):
        self.input_mode = True
        self.input_label = label
        self.input_buffer = initial
        self._input_cb = callback
        self._hist_pos = None

    def memory_label(self):
        if not self.config.get("behavior", "show_memory", default=True):
            return ""
        now = time.time()
        if now - self._mem_time > 2.0:
            self._mem_time = now
            ws, priv = memory.usage_mb()
            self._mem_label = f"RAM {ws:.0f} MB" if ws is not None else ""
        return self._mem_label

    def apply_config(self):
        self.viz_on = bool(self.config.get("behavior", "visualizer_enabled", default=True))
        self.audio.viz_enabled = self.viz_on
        self.trim_on = bool(self.config.get("behavior", "trim_memory", default=True))

    def _restore_preferences(self):
        b = self.config.get("behavior", default={}) or {}
        try:
            self.audio.set_volume(float(b.get("volume", 50)))
        except (TypeError, ValueError):
            pass
        self.playback.shuffle = bool(b.get("shuffle", False))
        self.playback.repeat = b.get("repeat", "off") if b.get("repeat") in ("off", "all", "one") else "off"

    def _save_preferences(self):
        self.config.set("behavior", "volume", round(self.audio.volume * 100))
        self.config.set("behavior", "shuffle", self.playback.shuffle)
        self.config.set("behavior", "repeat", self.playback.repeat)
        self.config.save()

    # ------------------------------------------------------------ loop
    def run(self):
        try:
            curses.curs_set(0)
        except curses.error:
            pass
        self.stdscr.keypad(True)
        self.theme.init()
        while self.running:
            self._safe_draw()
            self.stdscr.timeout(self._poll_ms())
            try:
                key = self.stdscr.getch()
            except KeyboardInterrupt:
                break
            except Exception:
                break
            if key == curses.KEY_RESIZE:
                self._on_resize()
            elif key != -1:
                try:
                    self.handle_key(key)
                except Exception as e:
                    log(f"key: {e}\n{traceback.format_exc()}")
                    self.notify("internal error")
            self._tick()

    def _poll_ms(self):
        a = self.audio
        if a.stage == "streaming" and not a.paused and self.viz_on:
            return 60                              # animação das barras
        if (self.playback.resolving_title or self.home.loading or a.stage == "opening"
                or self.screens["search"].loading):
            return 100                             # spinner
        return 250                                 # parado: quase nada de CPU

    def _on_resize(self):
        try:
            curses.update_lines_cols()
        except Exception:
            pass
        self.stdscr.clear()

    def _tick(self):
        self.playback.tick()
        self.screens[self.mode].tick()
        a = self.audio
        if self.viz_on and a.stage == "streaming" and not a.paused:
            self.viz = list(a.levels)
        else:
            self.viz = [v * 0.8 for v in self.viz]
        self._auto_trim()

    def _auto_trim(self):
        """A cada ~1 min (e logo depois de começar uma faixa) devolve memória ociosa."""
        if not self.trim_on:
            return
        a, now = self.audio, time.time()
        due = now - self._trim_t > 60
        if a.stage == "streaming" and a.gen != self._trim_gen and a.time_pos > 4:
            due, self._trim_gen = True, a.gen
        if due:
            self._trim_t = now
            memory.trim()

    # ------------------------------------------------------------ desenho
    def _safe_draw(self):
        try:
            self.draw()
        except curses.error:
            pass
        except Exception as e:
            log(f"draw: {e}\n{traceback.format_exc()}")

    def draw(self):
        win = self.stdscr
        win.erase()
        h, w = win.getmaxyx()
        if h < MIN_H or w < MIN_W:
            put(win, 0, 0, f" terminal too small — minimum {MIN_W}x{MIN_H} ")
            win.refresh()
            return
        chrome.draw_header(self, w)
        chrome.draw_tabs(self, 3)
        self.screens[self.mode].draw(5, h - 17, w)
        chrome.draw_player(self, h, w)
        chrome.draw_search_bar(self, h - 4, w)
        chrome.draw_message(self, h - 3, w)
        chrome.draw_footer(self, h, w)
        if self.show_help:
            chrome.draw_help(self, h, w)
        win.refresh()

    # ------------------------------------------------------------ teclado
    def handle_key(self, key):
        if self.show_help:
            self.show_help = False
            return
        if self.input_mode:
            self._input_key(key)
            return
        if 65 <= key <= 90:                         # maiúsculas = minúsculas
            key += 32
        screen = self.screens[self.mode]
        if key in screen.captures_keys:
            screen.on_key(key)
            return
        if self._global_key(key):
            return
        screen.on_key(key)

    def _global_key(self, key):
        a, pb = self.audio, self.playback
        if key == ord("q"):
            self.running = False
        elif key == 27:
            if not self.screens[self.mode].on_escape():
                self.running = False
        elif key == ord(" "):
            a.toggle_pause()
        elif key == curses.KEY_RIGHT:
            a.seek(10)
        elif key == curses.KEY_LEFT:
            a.seek(-10)
        elif key in (ord("-"), ord("_")):
            a.set_volume(round(a.volume * 100) - 5)
        elif key in (ord("+"), ord("=")):
            a.set_volume(round(a.volume * 100) + 5)
        elif key == ord("m"):
            a.toggle_mute()
        elif key in (ord(">"), ord(".")):
            pb.next()
        elif key in (ord("<"), ord(",")):
            pb.prev()
        elif key == ord("\t"):
            self._step_tab(+1)
        elif key == curses.KEY_BTAB:
            self._step_tab(-1)
        elif ord("1") <= key <= ord("5"):
            self.set_mode(chrome.TABS[key - ord("1")][0])
        elif key == ord("/"):
            self.prompt("search", self.screens["search"].start)
        elif key == ord("s"):
            pb.toggle_shuffle()
        elif key == ord("r"):
            pb.cycle_repeat()
        elif key == ord("f"):
            item = self.screens[self.mode].cursor_item()
            if item:
                self.notify("added to queue" if self.queue.add(item) else "already in queue")
        elif key in (ord("?"), curses.KEY_F1):
            self.show_help = True
        else:
            return False
        return True

    def _step_tab(self, step):
        keys = [k for k, _ in chrome.TABS]
        self.set_mode(keys[(keys.index(self.mode) + step) % len(keys)])

    def _input_key(self, key):
        if key == 27:
            self.input_mode, self.input_buffer, self._input_cb = False, "", None
            return
        if key in (curses.KEY_ENTER, 10, 13):
            text, cb = self.input_buffer.strip(), self._input_cb
            self.input_mode, self.input_buffer, self._input_cb = False, "", None
            if self.input_label == "search" and text:
                if text in self._search_history:
                    self._search_history.remove(text)
                self._search_history.append(text)
                del self._search_history[:-50]            # histórico limitado
            if cb:
                cb(text)
            return
        if key in (curses.KEY_BACKSPACE, 8, 127):
            self.input_buffer = self.input_buffer[:-1]
        elif key == 21:                              # Ctrl+U limpa o campo
            self.input_buffer = ""
        elif key in (curses.KEY_UP, curses.KEY_DOWN) and self.input_label == "search":
            self._browse_history(-1 if key == curses.KEY_UP else 1)
        else:
            try:
                ch = chr(key)
                if ch.isprintable():
                    self.input_buffer += ch
            except (ValueError, OverflowError):
                pass

    def _browse_history(self, step):
        hist = self._search_history
        if not hist:
            return
        pos = len(hist) if self._hist_pos is None else self._hist_pos
        pos = max(0, min(len(hist), pos + step))
        self._hist_pos = pos
        self.input_buffer = hist[pos] if pos < len(hist) else ""

    # ------------------------------------------------------------ encerramento
    def shutdown(self):
        try:
            self._save_preferences()
        finally:
            self.audio.close()


# ---------------------------------------------------------------------- entrada
def _curses_main(stdscr):
    # Qualquer print perdido (de bibliotecas) quebraria a tela do curses.
    real_out, real_err = sys.stdout, sys.stderr
    devnull = open(os.devnull, "w")
    sys.stdout = sys.stderr = devnull
    app = None
    try:
        app = PlayerApp(stdscr)
        app.run()
    finally:
        sys.stdout, sys.stderr = real_out, real_err
        devnull.close()
        if app is not None:
            app.shutdown()
        log("=== FIM ===")


def test_audio():
    """python main.py --test-audio : toca um beep para testar a placa de som."""
    try:
        import math
        from array import array
        import sounddevice as sd
        sr = 44100
        n = int(sr * 0.4)
        tone = array("h", (int(0.15 * 32767 * math.sin(2 * math.pi * 660 * i / sr))
                           for i in range(n)))
        with sd.RawOutputStream(samplerate=sr, channels=1, dtype="int16") as out:
            out.write(tone.tobytes())
        print("Áudio OK — você deve ter ouvido um beep.")
        return 0
    except Exception as e:
        print(f"Falha no áudio: {e}\nVerifique a saída de som do Windows.")
        return 1


def main(argv=None):
    argv = list(argv or [])
    if "--version" in argv:
        print(f"TrecoTunes {__version__}")
        return 0
    if "--test-audio" in argv:
        return test_audio()

    ensure_dirs()
    migrate_legacy()
    reset_log()
    os.environ.setdefault("ESCDELAY", "25")          # ESC responde na hora (Linux/macOS)
    try:
        curses.wrapper(_curses_main)
    except KeyboardInterrupt:
        pass
    except Exception:
        log(f"CRASH:\n{traceback.format_exc()}")
        print("\nO TrecoTunes encontrou um erro. Detalhes em data\\logs\\player.log")
        return 1
    return 0
