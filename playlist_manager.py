import json
import os
import time
import uuid
from core import log

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))


class PlaylistManager:
    def __init__(self, path=None, history_path=None):
        self.path = path or os.path.join(SCRIPT_DIR, "playlists.json")
        self.history_path = history_path or os.path.join(SCRIPT_DIR, "history.json")
        self.playlists = []
        self.active_id = None
        self.history = []
        self._load_or_create()
        self._load_history()

    def _load_or_create(self):
        if not os.path.exists(self.path):
            self._create_initial()
            return
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.playlists = data.get("playlists", [])
            self.active_id = data.get("active_id")
            if not isinstance(self.playlists, list):
                raise ValueError("playlists not a list")
            if not self.playlists:
                self._create_initial()
            elif not self.active_id or not self.find(self.active_id):
                self.active_id = self.playlists[0]["id"]
                self._save()
        except Exception as e:
            log(f"playlists: invalid: {e}")
            try:
                os.replace(self.path, self.path + ".bak")
            except Exception:
                pass
            self._create_initial()

    def _load_history(self):
        if not os.path.exists(self.history_path):
            self.history = []
            return
        try:
            with open(self.history_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.history = data.get("items", [])
            if not isinstance(self.history, list):
                self.history = []
        except Exception as e:
            log(f"history: invalid: {e}")
            self.history = []

    def _save(self):
        try:
            tmp = self.path + ".tmp"
            data = {"version": 1, "playlists": self.playlists, "active_id": self.active_id}
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.path)
        except Exception as e:
            log(f"playlists write: {e}")

    def _save_history(self):
        try:
            tmp = self.history_path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "items": self.history}, f,
                          ensure_ascii=False, indent=2)
            os.replace(tmp, self.history_path)
        except Exception as e:
            log(f"history write: {e}")

    def _create_initial(self):
        self.playlists = []
        self.active_id = None
        p = self.create_playlist("Default")
        self.active_id = p["id"]
        self._save()

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
        if self.active_id == pid:
            self.active_id = self.playlists[0]["id"] if self.playlists else None
        self._save()

    def add_track(self, pid, track):
        p = self.find(pid)
        if not p:
            return False
        url = track.get("url")
        if not url:
            return False
        if any(t.get("url") == url for t in p["tracks"]):
            return False
        p["tracks"].append({
            "title": track.get("title", "?"),
            "url": url,
            "duration": track.get("duration", ""),
        })
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
        self.history.insert(0, {
            "title": track.get("title", "?"),
            "url": url,
            "duration": track.get("duration", ""),
            "played_at": time.time(),
        })
        if len(self.history) > limit:
            self.history = self.history[:limit]
        self._save_history()

    def get_history(self, limit=20):
        return self.history[:limit]