"""Funções utilitárias de texto/tempo."""
import unicodedata

SPINNER = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"


def char_width(ch):
    if unicodedata.east_asian_width(ch) in ("W", "F"):
        return 2
    if unicodedata.category(ch).startswith("C") or unicodedata.combining(ch):
        return 0
    return 1


def wcswidth(s):
    return sum(char_width(c) for c in s)


def truncate(s, width):
    """Corta o texto para caber em `width` colunas, terminando com '…'."""
    if width <= 0:
        return ""
    if wcswidth(s) <= width:
        return s
    out, w = [], 0
    for ch in s:
        cw = char_width(ch)
        if w + cw + 1 > width:
            break
        out.append(ch)
        w += cw
    return "".join(out) + "…"


def pad(s, width):
    """Corta e completa com espaços até exatamente `width` colunas."""
    s = truncate(s, width)
    return s + " " * max(0, width - wcswidth(s))


def fmt_time(seconds):
    try:
        s = int(seconds)
    except Exception:
        return "--:--"
    if s < 0:
        return "--:--"
    m, s = divmod(s, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m:02d}:{s:02d}"


def spinner_frame(t):
    return SPINNER[int(t * 10) % len(SPINNER)]
