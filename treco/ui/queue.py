import curses

from .base import Screen
from .widgets import draw_track_row, hline, nav_target, put, scroll_start


class QueueScreen(Screen):
    name = "queue"

    def __init__(self, app):
        super().__init__(app)
        self.sel = 0

    def draw(self, y0, h, w):
        app, win = self.app, self.app.stdscr
        tracks = app.queue.tracks
        put(win, y0, 2, "TEMPORARY QUEUE", app.c(2, curses.A_BOLD | curses.A_DIM))
        hline(win, y0 + 1, 2, w - 4, "─", app.c(2, curses.A_DIM))
        if not tracks:
            put(win, y0 + 3, 4, "— queue is empty —", app.c(2, curses.A_DIM))
            put(win, y0 + 4, 4, "press F on any track to queue it", app.c(2, curses.A_DIM))
            return
        self.sel = min(self.sel, len(tracks) - 1)
        rows = min(len(tracks), h - 3)
        start = scroll_start(self.sel, rows)
        for i in range(start, min(start + rows, len(tracks))):
            draw_track_row(app, y0 + 3 + i - start, 2, w - 4, tracks[i],
                           selected=(i == self.sel), index=i)

    def cursor_item(self):
        t = self.app.queue.tracks
        return t[self.sel] if 0 <= self.sel < len(t) else None

    def on_key(self, key):
        app, q = self.app, self.app.queue
        tracks = q.tracks
        new = nav_target(key, self.sel, len(tracks))
        if new is not None:
            self.sel = new
        elif key in (curses.KEY_ENTER, 10, 13) and tracks:
            app.playback.play_from("queue", None, self.sel)
        elif key == ord("d") and tracks:
            tr = q.remove(self.sel)
            self.sel = min(self.sel, max(0, len(q.tracks) - 1))
            if tr:
                app.notify(f"removed: {tr.get('title', '?')[:30]}")
        elif key == ord("j") and q.move(self.sel, 1):
            self.sel += 1
        elif key == ord("k") and q.move(self.sel, -1):
            self.sel -= 1
        elif key == ord("l"):
            q.clear()
            self.sel = 0
            app.notify("queue cleared")

    def footer(self):
        return [("ENTER", "play"), ("D", "del"), ("J/K", "move"), ("L", "clear")]
