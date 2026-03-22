from __future__ import annotations

import platform
import subprocess
from pathlib import Path
from typing import Callable

import torch
import whisper


LogFn = Callable[[str], None]


def _pick_device() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def _model_device(model) -> torch.device:
    return next(model.parameters()).device


def load_whisper_model(model_name: str, log: LogFn) -> whisper.Whisper:
    cuda_available = torch.cuda.is_available()
    mps_available = hasattr(torch.backends, "mps") and torch.backends.mps.is_available()
    log(
        "Torch runtime: "
        f"cuda_available={cuda_available}, "
        f"cuda_device_count={torch.cuda.device_count() if cuda_available else 0}, "
        f"mps_available={mps_available}"
    )
    device = _pick_device()
    try:
        model = whisper.load_model(model_name, device=device)
        actual_device = _model_device(model)
        log(f"Whisper device selected: {actual_device.type}")
        return model
    except Exception as exc:
        if device == "cpu":
            raise
        log(f"GPU init failed on {device}, falling back to CPU: {exc}")
        model = whisper.load_model(model_name, device="cpu")
        actual_device = _model_device(model)
        log(f"Whisper device selected: {actual_device.type}")
        return model


def download_audio(video_id: str, video_url: str, audio_dir: Path, log: LogFn) -> Path:
    output_template = str(audio_dir / f"{video_id}.%(ext)s")
    log(f"Downloading audio for {video_id}...")
    proc = subprocess.run(
        [
            "yt-dlp",
            "-f",
            "bestaudio/best",
            "-x",
            "--audio-format",
            "mp3",
            "-o",
            output_template,
            video_url,
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip() or f"yt-dlp failed for {video_id}")

    audio_path = audio_dir / f"{video_id}.mp3"
    if not audio_path.exists():
        matches = sorted(audio_dir.glob(f"{video_id}.*"))
        if not matches:
            raise FileNotFoundError(f"Audio file not found for {video_id}")
        audio_path = matches[0]

    log(f"Audio ready: {audio_path.name}")
    return audio_path


def _has_fast_dtw() -> bool:
    """Check if Triton is available for fast word-level DTW alignment.

    Triton is Linux-only; on Windows/macOS the fallback DTW is
    extremely slow on long audio and effectively freezes.
    """
    if platform.system() != "Linux":
        return False
    try:
        import triton  # noqa: F401
        return True
    except ImportError:
        return False


def transcribe_audio(model, audio_path: Path, log: LogFn) -> dict[str, object]:
    device = _model_device(model)
    use_fp16 = device.type == "cuda"
    use_word_ts = _has_fast_dtw()

    if use_word_ts:
        log(f"Transcribing {audio_path.name} with word timestamps...")
    else:
        log(f"Transcribing {audio_path.name} (word timestamps disabled — no Triton)...")

    result = model.transcribe(
        str(audio_path),
        # language="en",
        task="translate",
        word_timestamps=use_word_ts,
        verbose=False,
        fp16=use_fp16,
    )
    log("Transcription finished.")
    return result


def cleanup_audio_file(audio_path: Path, log: LogFn) -> None:
    if audio_path.exists():
        audio_path.unlink(missing_ok=True)
        log(f"Deleted temp audio: {audio_path.name}")
