"""Helpers de desenho compartilhados pelas telas."""
import curses

from ..utils import pad, wcswidth


def put(win, y, x, text, attr=0):
    """addstr seguro: nunca estoura a tela nem levanta curses.error."""
    try:
        h, w = win.getmaxyx()
        if y < 0 or y >= h or x < 0 or x >= w:
            return
        avail = w - x - (1 if y == h - 1 else 0)
        if avail <= 0:
            return
        if len(text) > avail:
            text = text[:avail]
        win.addstr(y, x, text, attr)
    except curses.error:
        pass


def hline(win, y, x, width, ch="─", attr=0):
    if width > 0:
        put(win, y, x, ch * width, attr)


def scroll_start(sel, visible):
    """Primeira linha visível: a lista só rola quando o cursor passa do fim."""
    return 0 if sel < visible else sel - visible + 1


def nav_target(key, sel, total, page=10):
    """Novo índice do cursor para ↑ ↓ PgUp PgDn Home End (ou None se não for navegação)."""
    if total <= 0:
        return None
    if key == curses.KEY_UP:
        new = sel - 1
    elif key == curses.KEY_DOWN:
        new = sel + 1
    elif key == curses.KEY_PPAGE:
        new = sel - page
    elif key == curses.KEY_NPAGE:
        new = sel + page
    elif key == curses.KEY_HOME:
        new = 0
    elif key == curses.KEY_END:
        new = total - 1
    else:
        return None
    return max(0, min(total - 1, new))


def draw_track_row(app, y, x, width, item, selected=False, index=None, focused=True):
    """Uma linha de faixa:  ▸ 01 Título ........ 03:45"""
    win = app.stdscr
    playing = bool(app.playback.url) and item.get("url") == app.playback.url
    if selected and focused:
        attr, num_attr = app.c(1, curses.A_BOLD), app.c(1, curses.A_DIM)
        marker = app.S_MARK
    elif playing:
        attr, num_attr = app.c(2), app.c(2, curses.A_DIM)
        marker = app.S_NOTE
    else:
        attr, num_attr = app.c(5), app.c(2, curses.A_DIM)
        marker = " "
    put(win, y, x, marker, attr)
    col = x + 2
    if index is not None:
        put(win, y, col, f"{index + 1:02d}", num_attr)
        col += 3
    dur = item.get("duration") or ""
    dur_w = wcswidth(dur) + 2 if dur else 1
    title_w = max(8, x + width - col - dur_w)
    put(win, y, col, pad(item.get("title", "?"), title_w), attr)
    if dur:
        put(win, y, x + width - len(dur) - 1, dur, app.c(2, curses.A_DIM))
