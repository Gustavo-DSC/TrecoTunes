import time
import uuid

from ..paths import HISTORY_FILE, PLAYLISTS_FILE
from .jsonstore import read_json, write_json


def _track(t):
    return {
        "title": t.get("title", "?"),
        "url": t.get("url"),
        "duration": t.get("duration", ""),
    }


class PlaylistManager:
    """Playlists (data/playlists.json) e histórico de reprodução (data/history.json)."""

    def __init__(self, path=None, history_path=None):
        self.path = str(path or PLAYLISTS_FILE)
        self.history_path = str(history_path or HISTORY_FILE)
        self.playlists = []
        self.active_id = None
        self.history = []
        self._load_playlists()
        self._load_history()

    # ---------- persistência ----------
    def _load_playlists(self):
        data = read_json(self.path)
        if isinstance(data, dict) and isinstance(data.get("playlists"), list) and data["playlists"]:
            self.playlists = data["playlists"]
            self.active_id = data.get("active_id")
            if not self.active_id or not self.find(self.active_id):
                self.active_id = self.playlists[0]["id"]
                self._save()
        else:
            self._create_initial()

    def _load_history(self):
        data = read_json(self.history_path)
        items = data.get("items") if isinstance(data, dict) else None
        self.history = items if isinstance(items, list) else []

    def _save(self):
        write_json(self.path, {"version": 1, "playlists": self.playlists,
                               "active_id": self.active_id})

    def _save_history(self):
        write_json(self.history_path, {"version": 1, "items": self.history})

    def _create_initial(self):
        self.playlists = []
        self.active_id = None
        p = self.create_playlist("Default")
        self.active_id = p["id"]
        self._save()

    # ---------- playlists ----------
    def get_all(self):
        return self.playlists

    def find(self, pid):
        for p in self.playlists:
            if p["id"] == pid:
                return p
        return None

    def create_playlist(self, name):
        p = {"id": str(uuid.uuid4()), "name": name, "tracks": [], "created": time.time()}
        self.playlists.append(p)
        if not self.active_id:
            self.active_id = p["id"]
        self._save()
        return p

    def rename_playlist(self, pid, new_name):
        p = self.find(pid)
        if not p:
            return False
        p["name"] = new_name
        self._save()
        return True

    def delete_playlist(self, pid):
        self.playlists = [p for p in self.playlists if p["id"] != pid]
        if not self.playlists:
            self._create_initial()
            return
        if self.active_id == pid:
            self.active_id = self.playlists[0]["id"]
        self._save()

    def add_track(self, pid, track):
        p = self.find(pid)
        url = track.get("url")
        if not p or not url:
            return False
        if any(t.get("url") == url for t in p["tracks"]):
            return False
        p["tracks"].append(_track(track))
        self._save()
        return True

    def remove_track(self, pid, idx):
        p = self.find(pid)
        if p and 0 <= idx < len(p["tracks"]):
            p["tracks"].pop(idx)
            self._save()
            return True
        return False

    def move_track(self, pid, idx, delta):
        p = self.find(pid)
        if not p:
            return False
        tracks = p["tracks"]
        new_idx = idx + delta
        if 0 <= idx < len(tracks) and 0 <= new_idx < len(tracks):
            tracks[idx], tracks[new_idx] = tracks[new_idx], tracks[idx]
            self._save()
            return True
        return False

    def get_active(self):
        return self.find(self.active_id) if self.active_id else None

    def set_active(self, pid):
        if self.find(pid):
            self.active_id = pid
            self._save()
            return True
        return False

    # ---------- histórico ----------
    def add_history(self, track, limit=50):
        url = track.get("url")
        if not url:
            return
        self.history = [h for h in self.history if h.get("url") != url]
        entry = _track(track)
        entry["played_at"] = time.time()
        self.history.insert(0, entry)
        del self.history[max(1, int(limit)):]
        self._save_history()

    def get_history(self, limit=20):
        return self.history[:limit]
