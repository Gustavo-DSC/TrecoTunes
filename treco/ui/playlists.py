import curses

from .base import Screen
from .widgets import draw_track_row, hline, nav_target, put, scroll_start
from ..utils import fmt_time, pad


class PlaylistsScreen(Screen):
    name = "playlist"

    def __init__(self, app):
        super().__init__(app)
        self.focus = "list"          # list | tracks
        self.cursor = 0
        self.track_cursor = 0

    # ---------------------------------------------------------------- helpers
    def _current(self):
        pls = self.app.playlists.get_all()
        return pls[self.cursor] if 0 <= self.cursor < len(pls) else None

    def on_escape(self):
        if self.focus == "tracks":
            self.focus = "list"
            return True
        return False

    def cursor_item(self):
        if self.focus != "tracks":
            return None
        pl = self._current()
        if pl and 0 <= self.track_cursor < len(pl["tracks"]):
            return pl["tracks"][self.track_cursor]
        return None

    # ---------------------------------------------------------------- desenho
    def draw(self, y0, h, w):
        app, win = self.app, self.app.stdscr
        left_w = min(30, max(20, w // 3))
        right_x = left_w + 2
        right_w = max(10, w - right_x - 2)
        for yy in range(y0, y0 + h):
            put(win, yy, left_w, "│", app.c(2, curses.A_DIM))
        put(win, y0, 2, "PLAYLISTS", app.c(2, curses.A_BOLD | curses.A_DIM))
        hline(win, y0 + 1, 2, left_w - 3, "─", app.c(2, curses.A_DIM))
        hline(win, y0 + 1, right_x, right_w, "─", app.c(2, curses.A_DIM))

        playlists = app.playlists.get_all()
        self.cursor = min(self.cursor, len(playlists))
        in_list = self.focus == "list"
        for i in range(min(len(playlists) + 1, h - 2)):
            y = y0 + 3 + i
            sel = (i == self.cursor)
            if i == len(playlists):
                attr = app.c(3, curses.A_BOLD) if sel and in_list else app.c(2, curses.A_DIM)
                put(win, y, 2, app.S_MARK if sel and in_list else " ", attr)
                put(win, y, 4, "+ new playlist", attr)
                continue
            pl = playlists[i]
            active = pl["id"] == app.playlists.active_id
            if sel and in_list:
                attr = app.c(1, curses.A_BOLD)
            elif active:
                attr = app.c(1)
            else:
                attr = app.c(5)
            put(win, y, 2, app.S_MARK if sel and in_list else " ", attr)
            put(win, y, 4, pad(f"{app.S_NOTE if active else ' '} {pl['name']}", left_w - 6), attr)

        pl = self._current()
        if pl is None:
            put(win, y0, right_x, "TRACKS", app.c(2, curses.A_BOLD | curses.A_DIM))
            return
        tracks = pl["tracks"]
        put(win, y0, right_x, f"TRACKS ({len(tracks)})", app.c(2, curses.A_BOLD | curses.A_DIM))
        if not tracks:
            put(win, y0 + 3, right_x, "— empty playlist —", app.c(2, curses.A_DIM))
            put(win, y0 + 4, right_x, "play something and press A", app.c(2, curses.A_DIM))
            return
        self.track_cursor = min(self.track_cursor, len(tracks) - 1)
        rows = min(len(tracks), h - 3)
        start = scroll_start(self.track_cursor, rows)
        for i in range(start, min(start + rows, len(tracks))):
            draw_track_row(app, y0 + 3 + i - start, right_x, right_w + 2, tracks[i],
                           selected=(i == self.track_cursor), index=i,
                           focused=(self.focus == "tracks"))

    # ---------------------------------------------------------------- teclas
    def on_key(self, key):
        if self.focus == "list":
            self._key_list(key)
        else:
            self._key_tracks(key)

    def _key_list(self, key):
        app = self.app
        pls = app.playlists.get_all()
        new = nav_target(key, self.cursor, len(pls) + 1)
        if new is not None:
            self.cursor = new
        elif key in (curses.KEY_ENTER, 10, 13):
            if self.cursor == len(pls):
                self._new()
            else:
                self.focus, self.track_cursor = "tracks", 0
        elif key == ord("n"):
            self._new()
        elif key == ord("e") and self.cursor < len(pls):
            pl = pls[self.cursor]
            app.prompt("rename", lambda t: self._rename(pl["id"], t), initial=pl["name"])
        elif key == ord("x") and self.cursor < len(pls):
            pl = pls[self.cursor]
            app.playlists.delete_playlist(pl["id"])
            self.cursor = min(self.cursor, max(0, len(app.playlists.get_all()) - 1))
            app.home.invalidate()
            app.notify(f"deleted: {pl['name']}")
        elif key == ord("a"):
            self._add_playing()
        elif key == ord("l") and self.cursor < len(pls):
            app.playlists.set_active(pls[self.cursor]["id"])
            app.home.invalidate()
            app.notify(f"active: {pls[self.cursor]['name']}")

    def _key_tracks(self, key):
        app = self.app
        pl = self._current()
        if not pl:
            self.focus = "list"
            return
        tracks = pl["tracks"]
        if key in (curses.KEY_BACKSPACE, 8, 127):
            self.focus = "list"
            return
        new = nav_target(key, self.track_cursor, len(tracks))
        if new is not None:
            self.track_cursor = new
        elif key in (curses.KEY_ENTER, 10, 13) and tracks:
            app.playlists.set_active(pl["id"])
            app.playback.play_from("playlist", pl["id"], self.track_cursor)
        elif key == ord("d") and tracks:
            tr = tracks[self.track_cursor]
            app.playlists.remove_track(pl["id"], self.track_cursor)
            self.track_cursor = min(self.track_cursor, max(0, len(pl["tracks"]) - 1))
            app.home.invalidate()
            app.notify(f"removed: {tr.get('title', '?')[:30]}")
        elif key in (ord("k"), ord("u")) and self.track_cursor > 0:
            app.playlists.move_track(pl["id"], self.track_cursor, -1)
            self.track_cursor -= 1
        elif key == ord("j") and self.track_cursor < len(tracks) - 1:
            app.playlists.move_track(pl["id"], self.track_cursor, 1)
            self.track_cursor += 1

    # ---------------------------------------------------------------- ações
    def _new(self):
        self.app.prompt("new playlist", self._create)

    def _create(self, text):
        if text:
            p = self.app.playlists.create_playlist(text)
            self.cursor = len(self.app.playlists.get_all()) - 1
            self.app.notify(f"created: {p['name']}")

    def _rename(self, pid, text):
        if text:
            self.app.playlists.rename_playlist(pid, text)
            self.app.home.invalidate()
            self.app.notify(f"renamed to: {text}")

    def _add_playing(self):
        app = self.app
        pb = app.playback
        pl = self._current()
        if not pb.url or not pl:
            return
        track = {"title": pb.title, "url": pb.url,
                 "duration": fmt_time(app.audio.duration) if app.audio.duration else ""}
        ok = app.playlists.add_track(pl["id"], track)
        app.home.invalidate()
        app.notify(f"added to {pl['name']}" if ok else "already in playlist")

    def footer(self):
        if self.focus == "list":
            return [("ENTER", "open"), ("N", "new"), ("E", "rename"), ("X", "del"),
                    ("A", "add playing"), ("L", "active")]
        return [("ENTER", "play"), ("D", "del"), ("J/K", "move"), ("F", "queue"),
                ("BS", "back")]
