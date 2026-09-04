"""Audio helpers: temp files, ffmpeg normalize to 16kHz mono."""
from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path


def save_upload_to_temp(data: bytes, suffix: str) -> Path:
    suffix = suffix if suffix.startswith(".") else f".{suffix}"
    fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="stt_")
    with open(fd, "wb") as f:
        f.write(data)
    return Path(tmp)


def normalize_to_wav_16k(src: Path) -> Path:
    """Convert any audio to 16kHz mono WAV via ffmpeg. Return src if ffmpeg missing."""
    if shutil.which("ffmpeg") is None:
        return src
    dst = src.with_suffix(".16k.wav")
    if dst.exists():
        return dst
    cmd = [
        "ffmpeg", "-y", "-i", str(src),
        "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
        str(dst),
    ]
    try:
        subprocess.run(cmd, check=True, capture_output=True)
        return dst
    except subprocess.CalledProcessError:
        return src
