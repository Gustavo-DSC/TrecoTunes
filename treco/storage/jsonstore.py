"""Leitura/escrita de JSON segura (escrita atômica + backup de arquivo corrompido)."""
import json
import os

from ..logger import log


def read_json(path):
    """Devolve o conteúdo ou None (se não existe ou está corrompido → vira .bak)."""
    path = str(path)
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        log(f"json inválido em {path}: {e}")
        try:
            os.replace(path, path + ".bak")
        except OSError:
            pass
        return None


def write_json(path, data):
    path = str(path)
    tmp = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except Exception as e:
        log(f"erro ao gravar {path}: {e}")
        return False
