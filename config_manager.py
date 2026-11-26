# config_manager.py
import json
import os
import copy
from core import log

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class ConfigManager:
    DEFAULT = {
        "version": 1,
        "_about": (
            "Cada cor pode ser: 'black','red','green','yellow','blue','magenta',"
            "'cyan','white','default', um inteiro 0-255, ou RGB [r,g,b]."
        ),
        "appearance": {
            "primary":   "green",
            "secondary": "cyan",
            "accent":    "yellow",
            "error":     "red",
            "text":      "white",
        },
        "behavior": {
            "visualizer_enabled": True,
        },
    }

    def __init__(self, path=None):
        self.path = path or os.path.join(SCRIPT_DIR, "config.json")
        self.data = self._load_or_create()

    def _default(self):
        return copy.deepcopy(self.DEFAULT)

    def _load_or_create(self):
        if not os.path.exists(self.path):
            log(f"config: creating default at {self.path}")
            d = self._default()
            self._write(d)
            return d
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = self._merge(self._default(), data)
            self._write(merged)
            return merged
        except Exception as e:
            log(f"config: invalid, recreating: {e}")
            try:
                os.replace(self.path, self.path + ".bak")
            except Exception:
                pass
            d = self._default()
            self._write(d)
            return d

    def _merge(self, default, user):
        if not isinstance(user, dict):
            return default
        out = copy.deepcopy(default)
        for k, v in user.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = self._merge(out[k], v)
            else:
                out[k] = v
        return out

    def _write(self, data):
        try:
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            log(f"config: write failed: {e}")

    def save(self):
        self._write(self.data)

    def get(self, *keys, default=None):
        d = self.data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d