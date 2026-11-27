"""Reprodução de áudio em uma thread própria.

As bibliotecas pesadas (av, numpy, sounddevice) só são importadas na primeira vez
que uma música realmente toca — assim o app aberto, sem tocar nada, fica leve.
"""
import threading
import time
import traceback

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
        self._stop = threading.Event()
        self._seek_req = None
        self._lock = threading.Lock()

    # ------------------------------------------------------------ API pública
    @property
    def effective_volume(self):
        return 0.0 if self.muted else self.volume

    def open(self, url, start=0.0, duration_hint=0.0):
        """Começa a tocar `url` (descartando o que estava tocando, sem travar a UI)."""
        self._stop.set()                       # avisa a thread antiga para sair
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
            for dt in ("float32", "int16"):
                try:
                    stream = sd.OutputStream(samplerate=sr, channels=2, dtype=dt,
                                             blocksize=BLOCK)
                    stream.start()
                    log(f"OUT OK sr={sr} dtype={dt}")
                    return stream, sr, dt
                except Exception as e:
                    last_err = e
        raise _DeviceError(f"sem saída de áudio ({str(last_err)[:60]})")

    def _run(self, gen, stop, url):
        container = out = None
        try:
            import av
            import numpy as np
            import sounddevice as sd

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

            cc = stream.codec_context
            src_sr = cc.sample_rate or 48000
            src_ch = 2
            try:
                if cc.layout is not None:
                    src_ch = cc.layout.nb_channels
            except Exception:
                pass
            out, sr, dtype = self._open_output(sd, src_sr)
            spectrum = _Spectrum(np, BANDS)
            written = 0
            last_beat = time.time()

            def do_seek(target):
                nonlocal written
                container.seek(int(target / stream.time_base), stream=stream)
                written = int(target * sr)
                self.time_pos = target

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
                    pcm = _to_stereo(np, frame, src_ch)          # float32 (n, 2) em [-1, 1]
                except Exception as e:
                    log(f"to_ndarray: {e}")
                    continue
                if pcm.shape[0] == 0:
                    continue
                if sr != src_sr and pcm.shape[0] > 1:            # placa não aceitou a taxa
                    ratio = sr / src_sr
                    idx = (np.arange(int(pcm.shape[0] * ratio)) / ratio).astype(int)
                    pcm = pcm[idx]
                if self.viz_enabled:
                    self.levels = spectrum.update(pcm, sr, self.levels)
                vol = self.effective_volume
                buf = pcm * vol if vol != 1.0 else pcm
                if dtype == "int16":
                    buf = np.clip(buf * 32767, -32768, 32767).astype(np.int16)
                out.write(np.ascontiguousarray(buf))
                written += pcm.shape[0]
                if stop.is_set():
                    break
                self.time_pos = written / sr
                self.stage = "streaming"

                if time.time() - last_beat > 30:
                    log(f"heartbeat pos={self.time_pos:.1f}s ram={_ram()}")
                    last_beat = time.time()

            if not stop.is_set():
                self.stage = "done"
        except Exception as e:
            if not stop.is_set():
                self.error = str(e)[:120]
                self.error_kind = "device" if isinstance(e, _DeviceError) else None
                self.stage = "error"
            log(f"LOOP EXC: {e}\n{traceback.format_exc()}")
        finally:
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


def _to_stereo(np, frame, src_ch):
    """Converte um frame decodificado (planar/packed, int/float, mono/5.1) em float32 estéreo."""
    arr = frame.to_ndarray()
    name = frame.format.name
    if name.endswith("p"):                      # planar: (canais, amostras)
        pcm = arr.T
    else:                                       # packed: (1, amostras*canais)
        pcm = arr.reshape(-1, max(1, src_ch))
    if name.startswith("s16"):
        pcm = pcm.astype(np.float32) / 32768.0
    elif name.startswith("s32"):
        pcm = pcm.astype(np.float32) / 2147483648.0
    elif name.startswith("u8"):
        pcm = (pcm.astype(np.float32) - 128.0) / 128.0
    else:
        pcm = pcm.astype(np.float32, copy=False)
    if pcm.shape[1] == 1:
        pcm = np.repeat(pcm, 2, axis=1)
    elif pcm.shape[1] > 2:
        pcm = pcm[:, :2]
    return pcm


class _Spectrum:
    """Espectro barato para o visualizador: banda = |projeção| em senos/cossenos (matmul).

    Evita np.fft de propósito (nenhum plano/cache interno é criado a cada chamada).
    """
    N = 512

    def __init__(self, np, bands):
        self.np, self.bands = np, bands
        self.sr = None
        self.win = np.hanning(self.N).astype(np.float32)
        self.tilt = np.linspace(0, 8, bands).astype(np.float32)

    def _build(self, sr):
        np = self.np
        freqs = np.geomspace(60, min(14000, sr / 2.2), self.bands)
        t = np.arange(self.N, dtype=np.float64) / sr
        ang = 2 * np.pi * freqs[:, None] * t[None, :]
        w = self.win[None, :]
        self.cos = (np.cos(ang) * w).astype(np.float32)
        self.sin = (np.sin(ang) * w).astype(np.float32)
        self.norm = 2.0 / float(self.win.sum())
        self.sr = sr

    def update(self, pcm, sr, old):
        np = self.np
        if pcm.shape[0] < self.N:
            return old
        if sr != self.sr:
            self._build(sr)
        seg = pcm[:self.N].mean(axis=1)
        mag = np.hypot(self.cos @ seg, self.sin @ seg) * self.norm     # ~amplitude da banda
        db = 20.0 * np.log10(mag + 1e-6)
        new = np.clip((db + 52.0 + self.tilt) / 46.0, 0.0, 1.0)
        return [float(max(a, b * 0.82)) for a, b in zip(new, old)]
