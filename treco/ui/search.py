import curses
import threading
import time

from ..utils import spinner_frame
from .base import Screen
from .widgets import draw_track_row, nav_target, put, scroll_start

PAGE = 15


class SearchScreen(Screen):
    name = "search"

    def __init__(self, app):
        super().__init__(app)
        self.query = ""
        self.items = []
        self.shown = 0
        self.sel = 0
        self.loading = False
        self._req = 0

    def start(self, text):
        """Dispara uma busca em segundo plano."""
        self.query = text
        if not text:
            return
        self.loading = True
        self.items, self.shown, self.sel = [], 0, 0
        self.app.mode = "search"
        self._req += 1
        my_id = self._req

        def worker():
            time.sleep(0.12)                      # buscas em sequência: só a última vai à rede
            if my_id != self._req:
                return
            results = self.app.youtube.search(text, total=50)
            if my_id != self._req:
                return
            self.items = results
            self.shown = min(PAGE, len(results))
            self.loading = False

        threading.Thread(target=worker, daemon=True, name="search").start()

    def tick(self):
        # rolagem infinita: libera mais itens quando o cursor chega perto do fim
        if not self.loading and self.shown < len(self.items) and self.sel >= self.shown - 3:
            self.shown = min(self.shown + PAGE, len(self.items))

    def draw(self, y0, h, w):
        app, win = self.app, self.app.stdscr
        if self.loading:
            put(win, y0 + 1, 4, "— searching… —", app.c(3))
            put(win, y0 + 2, 4, f"{spinner_frame(app.phase)} {self.query[:40]}",
                app.c(2, curses.A_DIM))
            return
        visible = self.items[:self.shown]
        if not visible:
            put(win, y0 + 1, 4, "— no results —", app.c(2, curses.A_DIM))
            put(win, y0 + 2, 4, "press / to search", app.c(2, curses.A_DIM))
            return
        self.sel = min(self.sel, len(visible) - 1)
        rows = min(len(visible), h)
        start = scroll_start(self.sel, rows)
        for i in range(start, min(start + rows, len(visible))):
            draw_track_row(app, y0 + i - start, 2, w - 4, visible[i],
                           selected=(i == self.sel), index=i)
        if self.shown >= len(self.items):
            put(win, y0 + min(len(visible) - start, h - 1), w - 16, "— end —",
                app.c(2, curses.A_DIM))

    def cursor_item(self):
        visible = self.items[:self.shown]
        return visible[self.sel] if 0 <= self.sel < len(visible) else None

    def on_key(self, key):
        visible = self.items[:self.shown]
        new = nav_target(key, self.sel, len(visible))
        if new is not None:
            self.sel = new
        elif key in (curses.KEY_ENTER, 10, 13) and visible:
            self.app.playback.play_list(self.items, self.sel)
        elif key == ord("a") and visible:
            self.app.add_to_active(visible[self.sel])

    def footer(self):
        return [("ENTER", "play"), ("F", "queue"), ("A", "add"), ("/", "new search")]
