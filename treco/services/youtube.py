"""Busca e resolução de áudio do YouTube (pytubefix só é importado quando preciso)."""
import gc
import threading
from collections import OrderedDict, namedtuple

from ..logger import log
from ..utils import fmt_time

AudioInfo = namedtuple("AudioInfo", "stream_url title length error")  # error: None|"live"|"fail"

MAX_CACHED_QUERIES = 8


class YouTubeService:
    def __init__(self):
        self._cache = OrderedDict()     # query -> lista de resultados
        self._lock = threading.Lock()
        self._net = threading.Semaphore(2)   # no máximo 2 consultas de rede ao mesmo tempo

    def search(self, query, total=50):
        """Lista de {'title','url','duration'}. Resultados ficam em cache por consulta."""
        query = (query or "").strip()
        if not query:
            return []
        with self._lock:
            cached = self._cache.get(query)
            if cached is not None:
                self._cache.move_to_end(query)
                return list(cached[:total])
        try:
            with self._net:
                return self._search_net(query, total)
        except Exception as e:
            log(f"SEARCH erro: {e}")
            return []
        finally:
            gc.collect()

    def _search_net(self, query, total):
        try:
            from pytubefix import Search
            s = Search(query)
            videos = list(s.videos)
            tries = 0
            while len(videos) < total and tries < 2:      # tenta pegar mais páginas
                tries += 1
                try:
                    s.get_next_results()
                except Exception:
                    break
                more = list(s.videos)
                if len(more) <= len(videos):
                    break
                videos = more

            results, seen = [], set()
            for v in videos:
                try:
                    url = v.watch_url
                    if url in seen:
                        continue
                    seen.add(url)
                    item = {"title": v.title, "url": url, "duration": ""}
                    length = getattr(v, "_length", None)      # só se já veio na busca
                    if isinstance(length, int) and length > 0:
                        item["duration"] = fmt_time(length)
                    results.append(item)
                except Exception:
                    pass
                if len(results) >= total:
                    break
            del s, videos
            log(f"SEARCH '{query}': {len(results)}")
            with self._lock:
                self._cache[query] = results
                while len(self._cache) > MAX_CACHED_QUERIES:
                    self._cache.popitem(last=False)
            return list(results)
        except Exception as e:
            log(f"SEARCH erro: {e}")
            return []

    def forget(self, query):
        with self._lock:
            self._cache.pop((query or "").strip(), None)

    def audio_info(self, video_url):
        """Resolve a URL direta do stream de áudio."""
        try:
            with self._net:
                return self._audio_info_net(video_url)
        finally:
            gc.collect()

    def _audio_info_net(self, video_url):
        try:
            from pytubefix import YouTube
            yt = YouTube(video_url)
            try:
                if getattr(yt, "is_live", False):
                    return AudioInfo(None, None, 0, "live")
            except Exception:
                pass
            stream = yt.streams.get_audio_only()
            if stream:
                info = AudioInfo(stream.url, yt.title, yt.length, None)
                log(f"YT '{info.title}'")
                return info
            return AudioInfo(None, None, 0, "fail")
        except Exception as e:
            if "streaming live" in str(e):
                return AudioInfo(None, None, 0, "live")
            log(f"YT erro: {e}")
            return AudioInfo(None, None, 0, "fail")
