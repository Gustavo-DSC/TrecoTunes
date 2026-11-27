"""Conteúdo da tela inicial.

- Seções locais (Recently Played / Continue) são montadas na hora, sem rede.
- Seções de recomendação (For You / Discover) vêm do YouTube e ficam salvas em
  data/home_cache.json — o app só volta à rede quando o cache envelhece.
"""
import threading
import time

from ..logger import log
from ..paths import HOME_CACHE_FILE
from ..storage.jsonstore import read_json, write_json

SECTION_SIZE = 6


class HomeFeed:
    def __init__(self, youtube, playlists, config):
        self.youtube = youtube
        self.playlists = playlists
        self.config = config
        self.remote = []            # [(titulo, itens)]
        self.loading = False
        self._sections = None
        self._cached_seed = None
        self._cached_ts = 0.0

    # ------------------------------------------------------------ montagem
    def invalidate(self):
        self._sections = None

    def sections(self):
        if self._sections is None:
            self._sections = self._local_sections() + self.remote
        return self._sections

    def _local_sections(self):
        out = []
        recent = self.playlists.get_history(limit=SECTION_SIZE)
        if recent:
            out.append(("Recently Played", recent))
        pl = self.playlists.get_active()
        if pl and pl["tracks"]:
            out.append((f"Continue · {pl['name']}", pl["tracks"][:SECTION_SIZE]))
        return out

    # ------------------------------------------------------------ remoto
    def _seed_query(self):
        recent = self.playlists.get_history(limit=1)
        seed = recent[0]["title"] if recent else "lofi hip hop"
        return f"{seed.split('·')[0].strip()[:30]} mix"

    def start(self):
        """Mostra o cache (se houver) e só consulta a rede se estiver velho."""
        cache = read_json(HOME_CACHE_FILE)
        if isinstance(cache, dict):
            try:
                self.remote = [(s["title"], s["items"]) for s in cache.get("sections", [])]
                self._cached_seed = cache.get("seed")
                self._cached_ts = float(cache.get("ts", 0))
                self.invalidate()
            except Exception:
                self.remote = []
        ttl = float(self.config.get("behavior", "home_cache_hours", default=6)) * 3600
        stale = (time.time() - self._cached_ts > ttl) or not self.remote
        if stale:
            self.refresh()

    def refresh(self, force=False):
        if self.loading:
            return
        self.loading = True
        threading.Thread(target=self._fetch, args=(force,), daemon=True,
                         name="home-feed").start()

    def _fetch(self, force=False):
        try:
            seed_q = self._seed_query()
            queries = [("For You", seed_q),
                       ("Discover", f"discover new music {time.localtime().tm_year}")]
            sections = []
            for title, q in queries:
                if force:
                    self.youtube.forget(q)
                items = self.youtube.search(q, total=15)
                if items:
                    sections.append((title, items[:SECTION_SIZE]))
            if not sections and not self.remote:
                items = self.youtube.search("lofi hip hop", total=15)
                if items:
                    sections.append(("Recommended", items[:SECTION_SIZE]))
            if sections:
                self.remote = sections
                self._cached_seed, self._cached_ts = seed_q, time.time()
                write_json(HOME_CACHE_FILE, {
                    "version": 1, "ts": self._cached_ts, "seed": seed_q,
                    "sections": [{"title": t, "items": i} for t, i in sections],
                })
                self.invalidate()
        except Exception as e:
            log(f"home feed erro: {e}")
        finally:
            self.loading = False
