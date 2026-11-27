"""Log simples em arquivo (data/logs/player.log), zerado a cada execução."""
import threading
import time

from .paths import LOG_FILE, ensure_dirs

_lock = threading.Lock()


def reset_log():
    try:
        ensure_dirs()
        LOG_FILE.write_text("", encoding="utf-8")
    except Exception:
        pass


def log(msg):
    try:
        with _lock, open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass
