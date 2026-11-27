"""Caminhos do projeto e migração dos arquivos antigos."""
import os
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ASSETS_DIR = ROOT / "assets"
DATA_DIR = ROOT / "data"
LOG_DIR = DATA_DIR / "logs"

CONFIG_FILE = DATA_DIR / "config.json"
PLAYLISTS_FILE = DATA_DIR / "playlists.json"
HISTORY_FILE = DATA_DIR / "history.json"
HOME_CACHE_FILE = DATA_DIR / "home_cache.json"
LOG_FILE = LOG_DIR / "player.log"

# Onde esses arquivos ficavam nas versões antigas (na raiz do projeto)
_LEGACY_FILES = ("config.json", "playlists.json", "history.json")


def ensure_dirs():
    LOG_DIR.mkdir(parents=True, exist_ok=True)


def migrate_legacy():
    """Move config/playlists/histórico da raiz para data/ (sem sobrescrever nada)."""
    ensure_dirs()
    for name in _LEGACY_FILES:
        for suffix in ("", ".bak"):
            old = ROOT / (name + suffix)
            new = DATA_DIR / (name + suffix)
            if old.exists() and not new.exists():
                try:
                    shutil.move(str(old), str(new))
                except OSError:
                    pass
    # log antigo na raiz não serve mais
    try:
        os.remove(ROOT / "player_debug.log")
    except OSError:
        pass
