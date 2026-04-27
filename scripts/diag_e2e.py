"""Standalone end-to-end diagnostic: mic → Whisper → OpenRouter → print.

Run: uv run python scripts/diag_e2e.py

Records 3 seconds from the default microphone, transcribes via the user's
current ConfigStore settings, polishes via OpenRouter (if key is set), and
prints every stage with timings. Bypasses Qt/EventBus/QRunnable entirely.
"""
from __future__ import annotations

import asyncio
import sys
import time
import wave
from pathlib import Path

import numpy as np
import sounddevice as sd

from soyle.core.config import ConfigStore
from soyle.core.postprocess import PostProcess
from soyle.core.transcriber import Transcriber
from soyle.ui.resources import prompt_path


def banner(msg: str) -> None:
    print()
    print("=" * 60)
    print(msg)
    print("=" * 60, flush=True)


def record(seconds: float = 3.0, sample_rate: int = 16000) -> np.ndarray:
    banner(f"STAGE 1 — Recording {seconds}s from mic (speak now!)")
    print("Listening...", flush=True)
    audio = sd.rec(int(seconds * sample_rate), samplerate=sample_rate, channels=1, dtype="float32")
    sd.wait()
    rms = float(np.sqrt(np.mean(audio.astype(np.float64) ** 2)))
    peak = float(np.max(np.abs(audio)))
    print(f"  → captured {len(audio)} samples @ {sample_rate} Hz")
    print(f"  → RMS={rms:.4f}, peak={peak:.4f}")
    if rms < 0.001:
        print("  ⚠ Audio is silent — check microphone!")
    return audio.reshape(-1)


def save_wav(audio: np.ndarray, path: Path, sample_rate: int = 16000) -> None:
    int16 = (np.clip(audio, -1.0, 1.0) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(int16.tobytes())


async def main() -> int:
    banner("STAGE 0 — Loading config")
    store = ConfigStore()
    cfg = store.load()
    api_key = store.get_api_key()
    print(f"  model={cfg.whisper.model}")
    print(f"  device={cfg.whisper.device}")
    print(f"  compute_type={cfg.whisper.compute_type}")
    print(f"  language={cfg.whisper.language}")
    print(f"  postprocess.enabled={cfg.postprocess.enabled}")
    print(f"  postprocess.model={cfg.postprocess.model}")
    print(f"  api_key_set={'yes' if api_key else 'no'}", flush=True)

    audio = record(seconds=3.0)
    wav_path = Path.cwd() / "diag_recording.wav"
    save_wav(audio, wav_path)
    print(f"  → saved recording to {wav_path}", flush=True)

    banner("STAGE 2 — Transcriber init + warm_up")
    t0 = time.monotonic()
    transcriber = Transcriber(
        model=cfg.whisper.model,
        device=cfg.whisper.device,
        compute_type=cfg.whisper.compute_type,
        language=cfg.whisper.language,
    )
    print(f"  → Transcriber() constructed in {time.monotonic() - t0:.2f}s", flush=True)
    t0 = time.monotonic()
    transcriber.warm_up()
    print(f"  → warm_up() took {time.monotonic() - t0:.2f}s (device={transcriber.device})", flush=True)

    banner("STAGE 3 — Transcribe real audio")
    t0 = time.monotonic()
    try:
        result = transcriber.transcribe(audio, sample_rate=16000)
    except Exception as exc:
        print(f"  ❌ transcribe raised: {type(exc).__name__}: {exc}")
        return 2
    print(f"  → transcribe() took {time.monotonic() - t0:.2f}s")
    print(f"  → language detected: {result.language}")
    print(f"  → segments: {len(result.segments)}")
    print(f"  → raw_text: {result.raw_text!r}", flush=True)

    if not result.raw_text.strip():
        print("  ⚠ Empty transcription result. Can't test polish.")
        return 0

    banner("STAGE 4 — PostProcess polish via OpenRouter")
    pp = PostProcess(
        config=cfg.postprocess,
        api_key=api_key,
        prompt_path=prompt_path(cfg.postprocess.prompt_file),
    )
    t0 = time.monotonic()
    polish = await pp.polish(result.raw_text, language=result.language or "ru")
    print(f"  → polish() took {time.monotonic() - t0:.2f}s")
    print(f"  → fallback={polish.fallback}")
    print(f"  → tokens_in={polish.tokens_in} tokens_out={polish.tokens_out}")
    print(f"  → latency_ms={polish.latency_ms}")
    print(f"  → final text: {polish.text!r}", flush=True)

    banner("ALL STAGES COMPLETE — pipeline works end-to-end")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
