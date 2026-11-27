import curses

from ..utils import spinner_frame
from .base import Screen
from .widgets import draw_track_row, nav_target, put, scroll_start


class HomeScreen(Screen):
    name = "home"

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0        # índice na lista "achatada" (cabeçalhos + faixas)

    def on_enter(self):
        self.app.home.invalidate()

    def _flat(self):
        flat = []
        for title, items in self.app.home.sections():
            flat.append(("header", title, None, 0))
            for i, it in enumerate(items):
                flat.append(("track", it, items, i))
        return flat

    def _fix_sel(self, flat):
        tracks = [i for i, e in enumerate(flat) if e[0] == "track"]
        if not tracks:
            self.sel = 0
        elif self.sel not in tracks:
            self.sel = min(tracks, key=lambda i: abs(i - self.sel))
        return tracks

    def draw(self, y0, h, w):
        app, win = self.app, self.app.stdscr
        flat = self._flat()
        tracks = self._fix_sel(flat)
        if not tracks:
            if app.home.loading:
                put(win, y0 + 1, 4, "— loading home… —", app.c(2, curses.A_DIM))
                put(win, y0 + 2, 4, f"{spinner_frame(app.phase)} fetching", app.c(3))
            else:
                put(win, y0 + 1, 4, "— nothing here yet —", app.c(2, curses.A_DIM))
                put(win, y0 + 2, 4, "press / to search  ·  U to refresh", app.c(2, curses.A_DIM))
            return
        visible = min(len(flat), h)
        start = scroll_start(self.sel, visible)
        if start > 0 and flat[start][0] == "track" and flat[start - 1][0] == "header":
            start -= 1                                  # não esconde o título da seção
        for j in range(start, min(start + visible, len(flat))):
            kind, data, _, idx = flat[j]
            y = y0 + (j - start)
            if kind == "header":
                put(win, y, 2, app.S_MARK, app.c(2, curses.A_BOLD))
                put(win, y, 4, data, app.c(2, curses.A_BOLD | curses.A_DIM))
            else:
                draw_track_row(app, y, 4, w - 6, data, selected=(j == self.sel))
        if app.home.loading:
            put(win, y0 + h - 1, w - 28, f"{spinner_frame(app.phase)} updating picks…",
                app.c(3, curses.A_DIM))

    def cursor_item(self):
        flat = self._flat()
        if 0 <= self.sel < len(flat) and flat[self.sel][0] == "track":
            return flat[self.sel][1]
        return None

    def on_key(self, key):
        app = self.app
        flat = self._flat()
        tracks = self._fix_sel(flat)
        if not tracks:
            if key in (ord("u"), curses.KEY_F5):
                app.home.refresh(force=True)
            return
        pos = tracks.index(self.sel)
        new = nav_target(key, pos, len(tracks))
        if new is not None:
            self.sel = tracks[new]
        elif key in (curses.KEY_ENTER, 10, 13):
            _, item, items, idx = flat[self.sel]
            app.playback.play_list(items, idx)
        elif key == ord("a"):
            app.add_to_active(flat[self.sel][1])
        elif key in (ord("u"), curses.KEY_F5):
            app.home.refresh(force=True)
            app.notify("atualizando recomendações…")

    def footer(self):
        return [("ENTER", "play"), ("F", "queue"), ("A", "add"), ("U", "refresh")]
