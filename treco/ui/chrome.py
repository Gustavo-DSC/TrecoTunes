"""Moldura do app: cabeçalho, abas, player, barra de busca, rodapé e ajuda."""
import curses
import time

from .. import APP_NAME, __version__
from ..utils import fmt_time, spinner_frame, truncate
from .widgets import hline, put

TABS = [("home", "HOME"), ("search", "SEARCH"), ("playlist", "PLAYLIST"),
        ("queue", "QUEUE"), ("settings", "CONFIG")]

HELP = [
    ("Playback", None),
    ("SPACE", "play / pause"),
    ("← →", "seek -10s / +10s"),
    ("> <   (. ,)", "next / previous track"),
    ("S", "shuffle on/off"),
    ("R", "repeat: off → all → one"),
    ("+ -   M", "volume / mute"),
    ("Navigation", None),
    ("TAB  1-5", "switch tab"),
    ("↑ ↓ PgUp PgDn", "move in lists"),
    ("ENTER", "play selected"),
    ("/", "search YouTube"),
    ("Library", None),
    ("F", "add selected to queue"),
    ("A", "add selected to active playlist"),
    ("Q  ESC", "quit"),
]


def draw_header(app, w):
    win = app.stdscr
    put(win, 0, 1, app.S_MARK, app.c(1, curses.A_BOLD))
    put(win, 0, 3, APP_NAME, app.c(1, curses.A_BOLD))
    x = 3 + len(APP_NAME) + 1
    put(win, 0, x, f"v{__version__}", app.c(2, curses.A_DIM))
    mem = app.memory_label()
    if mem:
        put(win, 0, x + len(__version__) + 3, mem, app.c(2, curses.A_DIM))

    a, pb = app.audio, app.playback
    if a.error:
        st, sc = "ERROR", 4
    elif pb.resolving_title or a.stage == "opening":
        st, sc = "LOADING", 3
    elif a.stage == "streaming" and not a.paused:
        st, sc = "PLAYING", 1
    elif a.stage == "streaming":
        st, sc = "PAUSED", 3
    else:
        st, sc = "ONLINE", 1
    label = f"{app.S_DOT} {st}"
    put(win, 0, w - len(label) - 2, label, app.c(sc, curses.A_BOLD))
    hline(win, 1, 0, w, "─", app.c(2, curses.A_DIM))


def draw_tabs(app, y):
    x = 2
    for key, label in TABS:
        active = app.mode == key
        attr = app.c(1, curses.A_BOLD) if active else app.c(2, curses.A_DIM)
        put(app.stdscr, y, x, app.S_MARK if active else app.S_CIRCLE, attr)
        put(app.stdscr, y, x + 2, label, attr)
        x += len(label) + 5


def draw_player(app, h, w):
    win, a, pb = app.stdscr, app.audio, app.playback
    hline(win, h - 11, 0, w, "═", app.c(2, curses.A_DIM))
    put(win, h - 10, 2, app.S_NOTE, app.c(1, curses.A_BOLD))

    if pb.resolving_title:
        title, t_attr = f"loading: {pb.resolving_title}", app.c(3)
    elif a.error:
        title, t_attr = f"erro: {a.error}", app.c(4, curses.A_BOLD)
    elif a.stage == "opening":
        title, t_attr = "abrindo stream...", app.c(3)
    elif a.stage == "done":
        title, t_attr = pb.title + "  [end]", app.c(2, curses.A_DIM)
    elif pb.url:
        title, t_attr = pb.title, app.c(5, curses.A_BOLD)
    else:
        title, t_attr = "no track loaded", app.c(2, curses.A_DIM)
    put(win, h - 10, 4, truncate(title, w - 8), t_attr)

    # barra de progresso
    pos, dur = a.time_pos, a.duration
    bar_x, bar_w = 2, w - 4
    if dur > 0:
        filled = int(min(1.0, max(0.0, pos / dur)) * (bar_w - 1))
        put(win, h - 9, bar_x, "━" * filled, app.c(1, curses.A_BOLD))
        put(win, h - 9, bar_x + filled, app.S_DOT, app.c(1, curses.A_BOLD))
        hline(win, h - 9, bar_x + filled + 1, bar_w - filled - 1, "─", app.c(2, curses.A_DIM))
    else:
        hline(win, h - 9, bar_x, bar_w, "─", app.c(2, curses.A_DIM))

    # ícone + tempo + modos + volume
    if a.paused or not pb.url:
        icon, icon_attr = app.S_PAUSE, app.c(3, curses.A_BOLD)
    else:
        icon, icon_attr = app.S_PLAY, app.c(1, curses.A_BOLD)
    put(win, h - 8, 2, icon, icon_attr)
    time_str = f"{fmt_time(pos)}  ·  {fmt_time(dur) if dur else '--:--'}"
    put(win, h - 8, 5, time_str, app.c(2, curses.A_DIM))
    parts = []
    if pb.shuffle:
        parts.append("⇄ SHF")
    if pb.repeat == "all":
        parts.append("↻ ALL")
    elif pb.repeat == "one":
        parts.append("↻ 1")
    if parts:
        txt = "  ".join(parts)
        put(win, h - 8, max(5 + len(time_str) + 3, (w - len(txt)) // 2), txt,
            app.c(1, curses.A_BOLD))
    vol = "MUTE" if a.muted else f"{int(a.volume * 100):3d}%"
    vol_str = f"VOL {vol}"
    put(win, h - 8, w - len(vol_str) - 2, vol_str,
        app.c(4 if a.muted else 2, curses.A_DIM))

    # visualizador
    if app.viz_on:
        n_bars = min(len(app.viz), max(10, w - 16))
        for i in range(n_bars):
            v = app.viz[i]
            ch = app.VIZ[int(v * (len(app.VIZ) - 1))]
            if v < 0.1:
                attr = app.c(2, curses.A_DIM)
            elif v > 0.65:
                attr = app.c(1, curses.A_BOLD)
            else:
                attr = app.c(1)
            put(win, h - 7, 2 + i, ch, attr)
    hline(win, h - 6, 0, w, "═", app.c(2, curses.A_DIM))


def draw_search_bar(app, y, w):
    win = app.stdscr
    search = app.screens["search"]
    put(win, y, 2, app.S_SEARCH if app.input_label == "search" else "✎",
        app.c(3, curses.A_BOLD) if app.input_mode else app.c(2, curses.A_DIM))
    if app.input_mode:
        x = 4
        if app.input_label != "search":
            put(win, y, x, app.input_label + ":", app.c(2, curses.A_DIM))
            x += len(app.input_label) + 2
        avail = w - x - 3
        text = app.input_buffer
        shown = text[-avail:] if len(text) > avail else text
        put(win, y, x, shown, app.c(5))
        put(win, y, x + len(shown), " ", curses.A_REVERSE)
    elif search.loading:
        put(win, y, 4, f"{spinner_frame(app.phase)} searching {search.query[:40]}", app.c(3))
    elif search.query:
        put(win, y, 4, truncate(search.query, w - 8), app.c(2))
    else:
        put(win, y, 4, "press / to search", app.c(2, curses.A_DIM))


def draw_footer(app, h, w):
    win = app.stdscr
    hline(win, h - 2, 0, w, "─", app.c(2, curses.A_DIM))
    if app.input_mode:
        keys = [("ENTER", "confirm"), ("ESC", "cancel")]
        if app.input_label == "search":
            keys.append(("↑↓", "history"))
    else:
        keys = app.screens[app.mode].footer() + [
            ("SPACE", "pause"), ("<>", "skip"), ("S", "shuffle"), ("R", "repeat"),
            ("TAB", "tab"), ("/", "search"), ("?", "help"), ("Q", "quit")]
    x = 1
    for k, label in keys:
        if x + len(k) + len(label) + 2 > w - 1:
            break
        put(win, h - 1, x, k, app.c(1, curses.A_DIM))
        x += len(k) + 1
        put(win, h - 1, x, label, app.c(2, curses.A_DIM))
        x += len(label) + 2


def draw_message(app, y, w):
    if not app.message:
        return
    if time.time() - app.msg_time < 3.0:
        put(app.stdscr, y, 2, truncate(app.message, w - 4), app.c(5, curses.A_BOLD))
    else:
        app.message = ""


def draw_help(app, h, w):
    win = app.stdscr
    width = min(w - 4, 52)
    height = len(HELP) + 4
    x0, y0 = (w - width) // 2, max(0, (h - height) // 2)
    for r in range(height):
        put(win, y0 + r, x0, " " * width, 0)
    put(win, y0, x0, "┌" + "─" * (width - 2) + "┐", app.c(1))
    put(win, y0 + height - 1, x0, "└" + "─" * (width - 2) + "┘", app.c(1))
    for r in range(1, height - 1):
        put(win, y0 + r, x0, "│", app.c(1))
        put(win, y0 + r, x0 + width - 1, "│", app.c(1))
    put(win, y0 + 1, x0 + 2, f"{APP_NAME} — atalhos", app.c(1, curses.A_BOLD))
    for i, (k, d) in enumerate(HELP):
        y = y0 + 2 + i
        if d is None:
            put(win, y, x0 + 2, k, app.c(2, curses.A_BOLD | curses.A_DIM))
        else:
            put(win, y, x0 + 3, k, app.c(3))
            put(win, y, x0 + 20, d, app.c(5))
