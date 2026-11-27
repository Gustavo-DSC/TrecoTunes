import copy

from .paths import CONFIG_FILE
from .storage.jsonstore import read_json, write_json


class ConfigManager:
    """Configurações em data/config.json (campos novos são mesclados automaticamente)."""

    DEFAULT = {
        "version": 2,
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
            "visualizer_enabled": True,   # barras animadas (gasta um pouco de CPU)
            "show_memory": True,          # mostra o uso de RAM no cabeçalho
            "history_limit": 50,
            "home_cache_hours": 6,        # a Home só busca recomendações após esse tempo
            "volume": 50,
            "shuffle": False,
            "repeat": "off",              # off | all | one
        },
    }

    def __init__(self, path=None):
        self.path = str(path or CONFIG_FILE)
        raw = read_json(self.path)
        self.data = self._merge(self._default(), raw) if isinstance(raw, dict) else self._default()
        write_json(self.path, self.data)

    def _default(self):
        return copy.deepcopy(self.DEFAULT)

    def _merge(self, default, user):
        out = copy.deepcopy(default)
        for k, v in user.items():
            if k in out and isinstance(out[k], dict) and isinstance(v, dict):
                out[k] = self._merge(out[k], v)
            else:
                out[k] = v
        return out

    def save(self):
        write_json(self.path, self.data)

    def get(self, *keys, default=None):
        d = self.data
        for k in keys:
            if isinstance(d, dict) and k in d:
                d = d[k]
            else:
                return default
        return d

    def set(self, section, key, value):
        self.data.setdefault(section, {})[key] = value
