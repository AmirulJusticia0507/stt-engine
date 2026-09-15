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
        self.provider = os.getenv("STT_PROVIDER", "local").lower()
        self.base_url = os.getenv("OPENAI_BASE_URL", "")
        compute_type = compute_type or os.getenv("STT_COMPUTE", "float16")
        self.device = device or self._detect_device()
        if self.device == "cpu" and compute_type in ("float16", "float32"):
            compute_type = "int8"
        self.compute_type = compute_type
        self._model = None
        self._client = None

    @staticmethod
    def _detect_device() -> str:
        try:
            import torch

            return "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:
            return "cpu"

    def _ensure_model(self):
        if self.provider == "openai":
            if self._client is not None:
                return self._client
            try:
                from openai import OpenAI
            except ImportError as e:
                raise RuntimeError(
                    "SDK openai belum terinstall. pip install openai"
                ) from e
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                raise RuntimeError("OPENAI_API_KEY belum dikonfigurasi")
            client_kwargs = {"api_key": api_key}
            if self.base_url:
                client_kwargs["base_url"] = self.base_url
            self._client = OpenAI(**client_kwargs)
            return self._client
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

    def _transcribe_with_openai(self, audio_path: Path, language: str) -> dict:
        client = self._ensure_model()
        with audio_path.open("rb") as audio_file:
            response = client.audio.transcriptions.create(
                model=self.model_size,
                file=(audio_path.name, audio_file, "audio/wav"),
                language=language,
                response_format="verbose_json",
                timestamp_granularities=["segment"],
            )

        segments = [
            {
                "start": round(float(getattr(segment, "start", 0)), 2),
                "end": round(float(getattr(segment, "end", 0)), 2),
                "text": getattr(segment, "text", "").strip(),
            }
            for segment in (getattr(response, "segments", None) or [])
        ]
        text = getattr(response, "text", "") or ""
        if not segments and text:
            segments = [{"start": 0, "end": 0, "text": text.strip()}]
        return {
            "detected_language": getattr(response, "language", language),
            "language_probability": None,
            "segments": segments,
            "text": text.strip(),
        }

    @property
    def status(self) -> dict:
        return {
            "model": self.model_size,
            "provider": self.provider,
            "device": self.device,
            "compute_type": self.compute_type,
            "loaded": self._model is not None or self._client is not None,
        }

    def switch_model(self, model_size: str):
        """Ganti model saat runtime; model lama di-unload, yang baru lazy-load."""
        allowed = {"tiny", "base", "small", "medium", "large-v3", "large-v3-turbo"}
        if self.provider != "openai" and model_size not in allowed:
            raise ValueError(f"Model harus salah satu: {sorted(allowed)}")
        self.model_size = model_size
        old, self._model = self._model, None
        try:
            if old is not None:
                del old
        except Exception:
            pass
        try:
            import gc

            gc.collect()
            import torch

            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception:
            pass
        return self.status

    def transcribe_file(self, audio_path: str | Path, language: str = "id") -> dict:
        from app.utils import normalize_to_wav_16k

        wav = normalize_to_wav_16k(Path(audio_path))
        if self.provider == "openai":
            return self._transcribe_with_openai(wav, language)

        model = self._ensure_model()
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
