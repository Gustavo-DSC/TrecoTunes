"""Log simples em arquivo (data/logs/player.log), zerado a cada execução.

Tem limite de tamanho (gira para player.log.1 ao passar de 256 KB) e ignora a mesma
mensagem repetida em poucos segundos — assim um erro em loop não enche o disco.
"""
import os
import threading
import time

from .paths import LOG_FILE, ensure_dirs

MAX_BYTES = 256 * 1024
_lock = threading.Lock()
_size = 0
_last_msg = None
_last_time = 0.0


def reset_log():
    global _size, _last_msg
    try:
        ensure_dirs()
        LOG_FILE.write_text("", encoding="utf-8")
        _size, _last_msg = 0, None
    except Exception:
        pass


def log(msg):
    global _size, _last_msg, _last_time
    try:
        with _lock:
            now = time.time()
            if msg == _last_msg and now - _last_time < 5.0:
                return
            _last_msg, _last_time = msg, now
            line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
            if _size > MAX_BYTES:
                try:
                    os.replace(LOG_FILE, str(LOG_FILE) + ".1")
                except OSError:
                    pass
                _size = 0
            with open(LOG_FILE, "a", encoding="utf-8") as f:
                f.write(line)
            _size += len(line)
    except Exception:
        pass
