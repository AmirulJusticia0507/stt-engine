"""Core Faster-Whisper wrapper with lazy load + CPU fallback."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger("stt-engine")


class SpeechToTextEngine:
    def __init__(
        self,
        model_size: str | None = None,
        device: str | None = None,
        compute_type: str | None = None,
    ):
        # STT_MODEL=tiny di CPU kentang, large-v3-turbo di GPU (lihat blueprint)
        self.model_size = model_size or os.getenv("STT_MODEL", "large-v3-turbo")
        compute_type = compute_type or os.getenv("STT_COMPUTE", "float16")
        self.device = device or self._detect_device()
        if self.device == "cpu" and compute_type in ("float16", "float32"):
            compute_type = "int8"
        self.compute_type = compute_type
        self._model = None

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _ensure_model(self):
        if self._model is not None:
            return self._model
        try:
            from faster_whisper import WhisperModel
        except ImportError as e:
            raise RuntimeError(
                "faster-whisper belum terinstall. pip install faster-whisper torch"
            ) from e
        logger.info(
            "Loading Whisper '%s' on %s (%s)...",
            self.model_size, self.device, self.compute_type,
        )
        self._model = WhisperModel(
            model_size_or_path=self.model_size,
            device=self.device,
            compute_type=self.compute_type,
        )
        logger.info("Model loaded.")
        return self._model

    @property
    def status(self) -> dict:
        return {
            "model": self.model_size,
            "device": self.device,
            "compute_type": self.compute_type,
            "loaded": self._model is not None,
        }

    def transcribe_file(self, audio_path: str | Path, language: str = "id") -> dict:
        from app.utils import normalize_to_wav_16k

        model = self._ensure_model()
        wav = normalize_to_wav_16k(Path(audio_path))
        segments, info = model.transcribe(
            str(wav),
            language=language,
            beam_size=5,
            vad_filter=True,
            vad_parameters=dict(min_silence_duration_ms=500),
        )
        results = [
            {"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
            for s in segments
        ]
        return {
            "detected_language": info.language,
            "language_probability": round(info.language_probability, 2),
            "segments": results,
            "text": " ".join(r["text"] for r in results),
        }


# Singleton (model di-load lazy saat request pertama, bukan saat import)
stt_service = SpeechToTextEngine()
