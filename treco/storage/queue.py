class QueueManager:
    """Fila temporária em memória — some ao fechar o app."""

    def __init__(self):
        self.tracks = []

    def add(self, track):
        url = track.get("url")
        if not url:
            return False
        if any(t.get("url") == url for t in self.tracks):
            return False
        self.tracks.append({
            "title": track.get("title", "?"),
            "url": url,
            "duration": track.get("duration", ""),
        })
        return True

    def remove(self, idx):
        if 0 <= idx < len(self.tracks):
            return self.tracks.pop(idx)
        return None

    def clear(self):
        self.tracks = []

    def move(self, idx, delta):
        new_idx = idx + delta
        if 0 <= idx < len(self.tracks) and 0 <= new_idx < len(self.tracks):
            self.tracks[idx], self.tracks[new_idx] = self.tracks[new_idx], self.tracks[idx]
            return True
        return False

    def __len__(self):
        return len(self.tracks)
