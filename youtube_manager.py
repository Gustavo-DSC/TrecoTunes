import io
import contextlib
import threading
import time
from pytubefix import YouTube, Search
from core import log


class YouTubeManager:
    def __init__(self):
        self._cache = {}      # query -> full list of results
        self._cache_lock = threading.Lock()
        self._search_locks = {}

    def search_initial(self, query, total=50):
        """Retorna primeiros 15, mas faz fetch de `total` upfront."""
        if not query:
            return []
        with self._cache_lock:
            cached = self._cache.get(query)
        if cached is not None:
            return cached[:15]
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                s = Search(query)
                results = []
                for v in list(s.videos)[:total]:
                    try:
                        results.append({"title": v.title, "url": v.watch_url})
                    except Exception:
                        pass
            with self._cache_lock:
                self._cache[query] = results
            log(f"SEARCH '{query}': {len(results)} (cached)")
            return results[:15]
        except Exception as e:
            log(f"SEARCH erro: {e}")
            return []

    def get_cached(self, query):
        with self._cache_lock:
            return list(self._cache.get(query, []))

    def search_more(self, query, current_shown, page_size=15):
        """Retorna próximos `page_size` do cache (não faz nova request)."""
        with self._cache_lock:
            all_results = self._cache.get(query, [])
        start = current_shown
        end = start + page_size
        return all_results[start:end], len(all_results)

    def get_audio_info(self, video_url):
        try:
            with contextlib.redirect_stdout(io.StringIO()), \
                 contextlib.redirect_stderr(io.StringIO()):
                yt = YouTube(video_url)
                try:
                    if getattr(yt, "is_live", False):
                        return None, "LIVE", 0
                except Exception:
                    pass
                stream = yt.streams.get_audio_only()
                if stream:
                    log(f"YT '{yt.title}'")
                    return stream.url, yt.title, yt.length
            return None, None, 0
        except Exception as e:
            if "streaming live" in str(e):
                return None, "LIVE", 0
            log(f"YT erro: {e}")
            return None, None, 0