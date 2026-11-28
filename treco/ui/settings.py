import curses
import os

from .. import memory
from ..theme import Theme
from .base import Screen
from .widgets import hline, put

TOGGLES = [
    ("visualizer_enabled", "visualizer", "barras animadas (usa um pouco de CPU)"),
    ("show_memory", "RAM monitor", "mostra o uso de memória no topo"),
    ("trim_memory", "RAM trim", "libera memória ociosa de tempos em tempos"),
]


class SettingsScreen(Screen):
    name = "settings"
    captures_keys = (curses.KEY_LEFT, curses.KEY_RIGHT)

    def __init__(self, app):
        super().__init__(app)
        self.cursor = 0

    def _count(self):
        return len(Theme.SLOTS) + len(TOGGLES)

    def draw(self, y0, h, w):
        app, win = self.app, self.app.stdscr
        put(win, y0, 2, "APPEARANCE", app.c(2, curses.A_BOLD | curses.A_DIM))
        hline(win, y0 + 1, 2, 20, "─", app.c(2, curses.A_DIM))
        y = y0 + 3
        for i, slot in enumerate(Theme.SLOTS):
            sel = i == self.cursor
            current = app.config.get("appearance", slot, default="default")
            put(win, y, 2, app.S_MARK if sel else " ", app.c(1, curses.A_BOLD) if sel else 0)
            put(win, y, 4, slot.ljust(11), app.c(1, curses.A_BOLD) if sel else app.c(2))
            put(win, y, 17, str(current), app.c(i + 1, curses.A_BOLD))
            y += 1

        y += 1
        put(win, y, 2, "BEHAVIOR", app.c(2, curses.A_BOLD | curses.A_DIM))
        hline(win, y + 1, 2, 20, "─", app.c(2, curses.A_DIM))
        y += 3
        for j, (key, label, hint) in enumerate(TOGGLES):
            i = len(Theme.SLOTS) + j
            sel = i == self.cursor
            on = bool(app.config.get("behavior", key, default=True))
            put(win, y, 2, app.S_MARK if sel else " ", app.c(1, curses.A_BOLD) if sel else 0)
            put(win, y, 4, label.ljust(13), app.c(1, curses.A_BOLD) if sel else app.c(2))
            put(win, y, 18, "on " if on else "off", app.c(1 if on else 4, curses.A_BOLD))
            put(win, y, 23, hint, app.c(2, curses.A_DIM))
            y += 1

        y += 1
        ws, priv = memory.usage_mb()
        if ws is not None:
            txt = f"RAM do app: {ws:.0f} MB"
            if priv is not None:
                txt += f"  (privada {priv:.0f} MB)"
            put(win, y, 2, txt, app.c(2, curses.A_DIM))
            y += 1
        put(win, y, 2, "← → alterna    cores RGB: edite data/" + os.path.basename(app.config.path),
            app.c(2, curses.A_DIM))

    def on_key(self, key):
        app = self.app
        n = self._count()
        if key == curses.KEY_UP:
            self.cursor = max(0, self.cursor - 1)
        elif key == curses.KEY_DOWN:
            self.cursor = min(n - 1, self.cursor + 1)
        elif key in (curses.KEY_LEFT, curses.KEY_RIGHT, curses.KEY_ENTER, 10, 13):
            if self.cursor < len(Theme.SLOTS):
                slot = Theme.SLOTS[self.cursor]
                app.notify(f"{slot} = {app.theme.cycle(slot)}")
            else:
                key_name, label, _ = TOGGLES[self.cursor - len(Theme.SLOTS)]
                new = not app.config.get("behavior", key_name, default=True)
                app.config.set("behavior", key_name, new)
                app.config.save()
                app.apply_config()
                app.notify(f"{label}: {'on' if new else 'off'}")

    def footer(self):
        return [("↑↓", "nav"), ("←→", "change")]
