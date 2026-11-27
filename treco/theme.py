import curses
import sys

from .logger import log

# No Windows, windows-curses passa o valor direto pro console em vez de traduzir
# curses.COLOR_* -> Windows console attribute. Por isso usamos os atributos do
# Windows diretamente:  0=black 1=blue 2=green 3=cyan 4=red 5=magenta 6=yellow 7=white
if sys.platform == "win32":
    NAMED_COLORS = {
        "black": 0, "red": 4, "green": 2, "yellow": 6,
        "blue": 1, "magenta": 5, "cyan": 3, "white": 7,
        "default": -1,
    }
else:
    NAMED_COLORS = {
        "black": 0, "red": 1, "green": 2, "yellow": 3,
        "blue": 4, "magenta": 5, "cyan": 6, "white": 7,
        "default": -1,
    }

COLOR_CYCLE = ["green", "cyan", "blue", "magenta", "yellow", "red", "white", "default"]
_custom_slots_used = {}
_next_custom_slot = 200


def _nearest_basic(r, g, b):
    if sys.platform == "win32":
        basics = {0: (0, 0, 0), 1: (0, 0, 200), 2: (0, 200, 0), 3: (0, 200, 200),
                  4: (200, 0, 0), 5: (200, 0, 200), 6: (200, 200, 0), 7: (220, 220, 220)}
    else:
        basics = {0: (0, 0, 0), 1: (200, 0, 0), 2: (0, 200, 0), 3: (200, 200, 0),
                  4: (0, 0, 200), 5: (200, 0, 200), 6: (0, 200, 200), 7: (220, 220, 220)}
    best, best_d = 7, float("inf")
    for code, (br, bg, bb) in basics.items():
        d = (r - br) ** 2 + (g - bg) ** 2 + (b - bb) ** 2
        if d < best_d:
            best_d, best = d, code
    return best


def resolve_color(value):
    global _next_custom_slot
    if value is None:
        return -1
    if isinstance(value, str):
        return NAMED_COLORS.get(value.strip().lower(), -1)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        iv = int(value)
        return iv if 0 <= iv < 256 else -1
    if isinstance(value, (list, tuple)) and len(value) == 3:
        try:
            r, g, b = [max(0, min(255, int(x))) for x in value]
        except Exception:
            return -1
        key = (r, g, b)
        if key in _custom_slots_used:
            return _custom_slots_used[key]
        try:
            if curses.can_change_color() and _next_custom_slot < 256:
                slot = _next_custom_slot
                _next_custom_slot += 1
                curses.init_color(slot, int(r * 1000 / 255), int(g * 1000 / 255),
                                  int(b * 1000 / 255))
                _custom_slots_used[key] = slot
                return slot
        except Exception:
            pass
        return _nearest_basic(r, g, b)
    return -1


class Theme:
    SLOTS = ["primary", "secondary", "accent", "error", "text"]

    def __init__(self, config):
        self.config = config
        self.has_colors = False
        self.refresh()

    def refresh(self):
        app = self.config.get("appearance", default={}) or {}
        self.primary = resolve_color(app.get("primary", "green"))
        self.secondary = resolve_color(app.get("secondary", "cyan"))
        self.accent = resolve_color(app.get("accent", "yellow"))
        self.error = resolve_color(app.get("error", "red"))
        self.text = resolve_color(app.get("text", "white"))

    def init(self):
        try:
            curses.start_color()
            try:
                curses.use_default_colors()
            except Exception:
                pass
            self._apply()
            self.has_colors = True
        except Exception as e:
            log(f"Theme init fail: {e}")
            self.has_colors = False

    def _apply(self):
        try:
            curses.init_pair(1, self.primary, -1)
            curses.init_pair(2, self.secondary, -1)
            curses.init_pair(3, self.accent, -1)
            curses.init_pair(4, self.error, -1)
            curses.init_pair(5, self.text, -1)
        except curses.error as e:
            log(f"Theme apply error: {e}")

    def reapply(self):
        self.refresh()
        if self.has_colors:
            self._apply()

    def pair(self, n):
        return curses.color_pair(n) if self.has_colors else 0

    def cycle(self, slot):
        current = self.config.get("appearance", slot, default="default")
        try:
            idx = COLOR_CYCLE.index(current)
        except (ValueError, AttributeError):
            idx = -1
        new = COLOR_CYCLE[(idx + 1) % len(COLOR_CYCLE)]
        self.config.set("appearance", slot, new)
        self.config.save()
        self.reapply()
        return new
