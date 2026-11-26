import time
import threading
import traceback
import numpy as np
import av
import sounddevice as sd
from core import log


class AudioController:
    def __init__(self):
        self.url = None
        self.paused = True
        self.loading = False
        self.volume = 0.5
        self.time_pos = 0.0
        self.duration = 0.0
        self.error = None
        self._thread = None
        self._stop_flag = False
        self._seek_request = None
        self._lock = threading.Lock()
        self._stage = "idle"

    def load(self, url):
        self._stop()
        self.url = url
        self.time_pos = 0.0
        self.duration = 0.0
        self.paused = True
        self.loading = True
        self.error = None
        self._stage = "idle"

    def play(self):
        if not self.url:
            return
        if self.paused and self._thread and self._thread.is_alive():
            self.paused = False
            return
        if not self._thread or not self._thread.is_alive():
            self._stop_flag = False
            self.paused = False
            self._thread = threading.Thread(target=self._play_loop, daemon=True)
            self._thread.start()

    def pause(self):
        self.paused = True

    def toggle_pause(self):
        if self.paused:
            self.play()
        else:
            self.pause()

    def seek(self, seconds):
        with self._lock:
            self._seek_request = max(0.0, self.time_pos + seconds)

    def seek_to(self, pos):
        with self._lock:
            self._seek_request = max(0.0, pos)

    def set_volume(self, vol):
        self.volume = max(0.0, min(1.0, vol / 100.0))

    def _stop(self):
        self._stop_flag = True
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=3)
        self._thread = None

    def _open_output(self, sample_rate, channels):
        last_err = None
        for sr in (sample_rate, 48000, 44100, 22050):
            for dt in ("float32", "int16"):
                try:
                    stream = sd.OutputStream(samplerate=sr, channels=channels,
                                             dtype=dt, blocksize=4096)
                    stream.start()
                    log(f"OUT OK sr={sr} ch={channels} dtype={dt}")
                    return stream, sr, dt
                except Exception as e:
                    last_err = e
        raise RuntimeError(f"Nenhuma config ok. Ultimo: {last_err}")

    def _play_loop(self):
        container = None
        out = None
        try:
            self._stage = "opening"
            log(f"LOOP abrindo {self.url[:100]}")
            container = av.open(self.url, timeout=15.0)
            stream = container.streams.audio[0]
            cc = stream.codec_context
            if stream.duration and stream.time_base:
                try:
                    self.duration = float(stream.duration * stream.time_base)
                except Exception:
                    pass
            sample_rate = cc.sample_rate or 48000
            channels = 2
            try:
                if cc.layout is not None:
                    channels = cc.layout.nb_channels
            except Exception:
                pass
            out, real_sr, dtype = self._open_output(sample_rate, channels)
            self.loading = False
            self._stage = "decoding"
            samples_written = 0
            last_beat = time.time()

            # aplica seek inicial se houver (para retomada pós-erro)
            with self._lock:
                initial_seek = self._seek_request
                if initial_seek is not None:
                    self._seek_request = None
            if initial_seek is not None:
                try:
                    container.seek(int(initial_seek / stream.time_base), stream=stream)
                    samples_written = int(initial_seek * real_sr)
                    self.time_pos = initial_seek
                    log(f"LOOP seek inicial {initial_seek:.1f}s")
                except Exception as e:
                    log(f"seek inicial erro: {e}")

            for frame in container.decode(stream):
                if self._stop_flag:
                    break
                while self.paused and not self._stop_flag:
                    time.sleep(0.03)
                if self._stop_flag:
                    break
                with self._lock:
                    target = self._seek_request
                    if target is not None:
                        self._seek_request = None
                if target is not None:
                    try:
                        container.seek(int(target / stream.time_base), stream=stream)
                        samples_written = int(target * real_sr)
                    except Exception as e:
                        log(f"seek erro: {e}")
                    continue
                try:
                    audio = frame.to_ndarray()
                except Exception as e:
                    log(f"to_ndarray: {e}")
                    continue
                if audio.ndim == 2:
                    if audio.shape[0] == channels and audio.shape[1] != channels:
                        audio = audio.T
                audio = audio.astype(np.float32)
                if audio.size and np.abs(audio).max() > 1.5:
                    audio = audio / 32768.0
                audio = audio * self.volume
                if real_sr != sample_rate and audio.shape[0] > 1:
                    ratio = real_sr / sample_rate
                    nl = int(audio.shape[0] * ratio)
                    if nl > 0:
                        idx = (np.arange(nl) / ratio).astype(int)
                        audio = audio[idx]
                if dtype == "int16":
                    audio = np.clip(audio * 32767, -32768, 32767).astype(np.int16)
                audio = np.ascontiguousarray(audio)
                try:
                    out.write(audio)
                except Exception as e:
                    log(f"write: {e}")
                    self.error = f"write: {e}"
                    self._stage = "error"
                    break
                samples_written += audio.shape[0]
                self.time_pos = samples_written / real_sr
                self._stage = "streaming"
                if time.time() - last_beat > 5:
                    log(f"heartbeat pos={self.time_pos:.1f}s")
                    last_beat = time.time()
            if self._stage != "error":
                self._stage = "done"
        except Exception as e:
            self.error = str(e)[:120]
            self._stage = "error"
            log(f"LOOP EXC: {e}\n{traceback.format_exc()}")
        finally:
            self.loading = False
            try:
                if out is not None:
                    out.stop()
                    out.close()
            except Exception:
                pass
            try:
                if container is not None:
                    container.close()
            except Exception:
                pass

    def close(self):
        self._stop()