"""Reprodução de áudio em uma thread própria (sem numpy).

As bibliotecas pesadas (av, sounddevice) só são importadas na primeira vez
que uma música realmente toca — assim o app aberto, sem tocar nada, fica leve.

Fluxo: PyAV decodifica -> AudioResampler já entrega PCM int16 estéreo na taxa da
placa -> audioop aplica o volume -> sounddevice (RawOutputStream) toca os bytes.
"""
import math
import threading
import time
import traceback
from array import array

from ..logger import log

BANDS = 36
BLOCK = 4096


class AudioPlayer:
    def __init__(self):
        self.url = None
        self.paused = True
        self.volume = 0.5
        self.muted = False
        self.time_pos = 0.0
        self.duration = 0.0
        self.error = None
        self.error_kind = None      # "device" quando é problema de placa de som
        self.stage = "idle"         # idle | opening | streaming | done | error
        self.levels = [0.0] * BANDS
        self.viz_enabled = True
        self.gen = 0                # identifica a "sessão" de reprodução atual

        self._thread = None
        self._out = None            # stream de saída atual (para cortar o antigo ao trocar de faixa)
        self._stop = threading.Event()
        self._seek_req = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ API pública
    @property
    def effective_volume(self):
        return 0.0 if self.muted else self.volume

    def open(self, url, start=0.0, duration_hint=0.0):
        """Começa a tocar `url` (descartando o que estava tocando, sem travar a UI)."""
        old_thread, old_out = self._thread, self._out
        self._stop.set()                       # avisa a thread antiga para sair
        if old_out is not None:
            try:
                old_out.abort()                # destrava uma escrita pendente e corta o som antigo
            except Exception:
                pass
        if (old_thread is not None and old_thread.is_alive()
                and old_thread is not threading.current_thread()):
            old_thread.join(timeout=0.4)       # não deixa threads/streams velhos acumulando
        self._stop = threading.Event()
        self.gen += 1
        self.url = url
        self.paused = False
        self.error = None
        self.error_kind = None
        self.stage = "opening"
        self.duration = float(duration_hint or 0.0)
        self.time_pos = float(start or 0.0)
        with self._lock:
            self._seek_req = float(start) if start and start > 0 else None
        self._thread = threading.Thread(target=self._run, args=(self.gen, self._stop, url),
                                        daemon=True, name="audio")
        self._thread.start()

    def toggle_pause(self):
        if not self.url:
            return
        if self.stage in ("done", "error"):    # a thread já acabou: recomeça
            self.open(self.url, 0.0, self.duration)
            return
        self.paused = not self.paused

    def pause(self):
        self.paused = True

    def seek(self, seconds):
        self.seek_to(self.time_pos + seconds)

    def seek_to(self, pos):
        if not self.url:
            return
        pos = max(0.0, float(pos))
        if self.duration > 2:
            pos = min(pos, self.duration - 1.0)
        if self._thread is not None and self._thread.is_alive():
            with self._lock:
                self._seek_req = pos
            self.time_pos = pos
        else:
            self.open(self.url, pos, self.duration)

    def set_volume(self, pct):
        self.volume = max(0.0, min(1.0, pct / 100.0))
        if self.volume > 0:
            self.muted = False

    def toggle_mute(self):
        self.muted = not self.muted

    def close(self):
        self._stop.set()
        t = self._thread
        if t is not None and t.is_alive():
            t.join(timeout=1.0)

    # ---------------------------------------------------------------- internos
    def _take_seek(self):
        with self._lock:
            req, self._seek_req = self._seek_req, None
        return req

    def _has_seek(self):
        return self._seek_req is not None

    def _open_output(self, sd, sample_rate):
        last_err = None
        for sr in (sample_rate, 48000, 44100, 22050):
            try:
                stream = sd.RawOutputStream(samplerate=sr, channels=2, dtype="int16",
                                            blocksize=BLOCK)
                stream.start()
                log(f"OUT OK sr={sr}")
                return stream, sr
            except Exception as e:
                last_err = e
        raise _DeviceError(f"sem saída de áudio ({str(last_err)[:60]})")

    def _run(self, gen, stop, url):
        container = out = None
        try:
            import av
            import sounddevice as sd
            try:
                import audioop                      # Python <= 3.12
            except ImportError:                     # 3.13+: pip install audioop-lts
                raise RuntimeError("falta o pacote audioop-lts (pip install audioop-lts)")

            log(f"LOOP abrindo {url[:100]}")
            container = av.open(url, timeout=15.0)
            stream = container.streams.audio[0]
            try:
                if stream.duration and stream.time_base:
                    self.duration = float(stream.duration * stream.time_base)
                elif container.duration:
                    self.duration = float(container.duration) / 1_000_000
            except Exception:
                pass

            try:
                stream.thread_type = "NONE"      # sem threads extras de decodificação (menos RAM)
            except Exception:
                pass

            src_sr = stream.codec_context.sample_rate or 48000
            out, sr = self._open_output(sd, src_sr)
            self._out = out

            def new_resampler():
                # qualquer formato/canais -> int16 estéreo na taxa da placa
                return av.AudioResampler(format="s16", layout="stereo", rate=sr)

            resampler = new_resampler()
            spectrum = _Spectrum(BANDS)
            written = 0
            last_beat = last_viz = time.time()

            def do_seek(target):
                nonlocal written, resampler
                container.seek(int(target / stream.time_base), stream=stream)
                resampler = new_resampler()          # descarta o que sobrou do trecho antigo
                written = int(target * sr)
                self.time_pos = target

            def play(rframe):
                """Toca um frame já em s16 estéreo. Retorna False se deve parar."""
                nonlocal written, last_viz
                n = rframe.samples
                if n <= 0:
                    return True
                pcm = bytes(memoryview(rframe.planes[0])[:n * 4])   # 2 canais * 2 bytes, uma só cópia
                now = time.time()
                if self.viz_enabled and now - last_viz > 0.04:
                    last_viz = now
                    self.levels = spectrum.update(pcm, sr, self.levels, audioop)
                vol = self.effective_volume
                out.write(audioop.mul(pcm, 2, vol) if vol != 1.0 else pcm)
                written += n
                self.time_pos = written / sr
                self.stage = "streaming"
                return not stop.is_set()

            first = self._take_seek()
            if first is not None:
                try:
                    do_seek(first)
                except Exception as e:
                    log(f"seek inicial erro: {e}")

            for frame in container.decode(stream):
                if stop.is_set():
                    break
                while self.paused and not stop.is_set() and not self._has_seek():
                    time.sleep(0.03)
                if stop.is_set():
                    break
                target = self._take_seek()
                if target is not None:
                    try:
                        do_seek(target)
                    except Exception as e:
                        log(f"seek erro: {e}")
                    continue

                try:
                    rframes = resampler.resample(frame)
                except Exception as e:
                    log(f"resample: {e}")
                    continue
                if rframes is None:
                    continue
                if not isinstance(rframes, (list, tuple)):    # versões antigas do PyAV
                    rframes = [rframes]
                keep = True
                for rf in rframes:
                    if not play(rf):
                        keep = False
                        break
                if not keep:
                    break

                if time.time() - last_beat > 30:
                    log(f"heartbeat pos={self.time_pos:.1f}s ram={_ram()}")
                    last_beat = time.time()

            if not stop.is_set():
                try:                                           # sobra do resampler
                    tail = resampler.resample(None)
                    if tail is not None:
                        for rf in (tail if isinstance(tail, (list, tuple)) else [tail]):
                            play(rf)
                except Exception:
                    pass
                self.stage = "done"
        except Exception as e:
            if not stop.is_set():
                self.error = str(e)[:120]
                self.error_kind = "device" if isinstance(e, _DeviceError) else None
                self.stage = "error"
            log(f"LOOP EXC: {e}\n{traceback.format_exc()}")
        finally:
            if self._out is out:
                self._out = None
            try:
                if out is not None:
                    if stop.is_set():
                        out.abort()          # corta na hora
                    else:
                        out.stop()           # deixa terminar o que já está no buffer
                    out.close()
            except Exception:
                pass
            try:
                if container is not None:
                    container.close()
            except Exception:
                pass
            if not stop.is_set():
                self.levels = [0.0] * BANDS


class _DeviceError(RuntimeError):
    pass


def _ram():
    try:
        from .. import memory
        ws, priv = memory.usage_mb()
        return f"{ws:.0f}MB" if ws else "?"
    except Exception:
        return "?"


class _Spectrum:
    """Visualizador simples, só para enfeite: Goertzel em Python puro.

    Pega 512 amostras, junta de 4 em 4 (128 pontos, ~12 kHz) e mede a energia de
    BANDS frequências (60 Hz até ~5 kHz). Custa ~1 ms por chamada e roda no máximo
    uns 25 vezes por segundo.
    """
    N = 512
    DEC = 4

    def __init__(self, bands):
        self.bands = bands
        self.sr = None
        self.coefs = []
        m = self.N // self.DEC
        self.win = [0.5 - 0.5 * math.cos(2 * math.pi * i / (m - 1)) for i in range(m)]
        self.norm = 2.0 / sum(self.win)
        self.tilt = [8.0 * i / max(1, bands - 1) for i in range(bands)]

    def _build(self, sr):
        eff = sr / self.DEC
        lo, hi = 60.0, min(5500.0, eff / 2.2)
        ratio = (hi / lo) ** (1.0 / max(1, self.bands - 1))
        self.coefs = [2.0 * math.cos(2 * math.pi * (lo * ratio ** i) / eff)
                      for i in range(self.bands)]
        self.sr = sr

    def update(self, pcm, sr, old, audioop):
        """pcm: bytes int16 estéreo. Devolve a lista de níveis (0..1) das barras."""
        need = self.N * 4
        if len(pcm) < need:
            return old
        if sr != self.sr:
            self._build(sr)
        samples = array("h")
        samples.frombytes(audioop.tomono(pcm[:need], 2, 0.5, 0.5))
        k = 1.0 / (self.DEC * 32768.0)
        d = [(samples[i] + samples[i + 1] + samples[i + 2] + samples[i + 3]) * k * w
             for i, w in zip(range(0, self.N, self.DEC), self.win)]
        norm, log10, sqrt = self.norm, math.log10, math.sqrt
        new = []
        for c, tilt in zip(self.coefs, self.tilt):
            s1 = s2 = 0.0
            for x in d:
                s1, s2 = x + c * s1 - s2, s1
            p = s1 * s1 + s2 * s2 - c * s1 * s2
            mag = sqrt(p) * norm if p > 0 else 0.0
            v = (20.0 * log10(mag + 1e-6) + 52.0 + tilt) / 46.0
            new.append(0.0 if v < 0 else 1.0 if v > 1 else v)
        return [max(a, b * 0.82) for a, b in zip(new, old)]
