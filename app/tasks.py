"""Celery tasks for async transcription."""
from __future__ import annotations

import base64
import logging
import tempfile
from pathlib import Path

from app.celery_app import celery_app
from app.stt_engine import stt_service
from app.auth import save_history, _session
from app.utils import normalize_to_wav_16k, save_upload_to_temp

logger = logging.getLogger("stt-engine.tasks")


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def transcribe_file_task(
    self,
    file_data_b64: str,
    filename: str,
    language: str,
    username: str | None,
    source_prefix: str = "upload",
) -> dict:
    """
    Transcribe audio file asynchronously.
    file_data_b64: base64 encoded file content
    """
    try:
        file_bytes = base64.b64decode(file_data_b64)
        suffix = Path(filename or "audio.wav").suffix or ".wav"
        tmp = save_upload_to_temp(file_bytes, suffix)

        try:
            result = stt_service.transcribe_file(tmp, language=language)

            if username and result.get("text"):
                try:
                    save_history(username, f"{source_prefix}:{filename}", language, result["text"], result)
                except Exception:
                    logger.exception("Failed to save history")

            return {
                "status": "success",
                "data": result,
                "filename": filename,
            }
        finally:
            tmp.unlink(missing_ok=True)
            tmp.with_suffix(".16k.wav").unlink(missing_ok=True)

    except Exception as exc:
        logger.exception("Transcription failed")
        # Retry on failure
        try:
            raise self.retry(exc=exc)
        except self.MaxRetriesExceededError:
            return {
                "status": "error",
                "detail": str(exc),
                "filename": filename,
            }


@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def transcribe_batch_task(
    self,
    files_data: list[dict],  # [{"filename": "...", "data_b64": "...", "language": "..."}]
    username: str | None,
) -> dict:
    """
    Transcribe multiple files asynchronously.
    """
    results = []
    for f in files_data:
        try:
            file_bytes = base64.b64decode(f["data_b64"])
            suffix = Path(f["filename"] or "audio.wav").suffix or ".wav"
            tmp = save_upload_to_temp(file_bytes, suffix)

            try:
                result = stt_service.transcribe_file(tmp, language=f.get("language", "id"))

                if username and result.get("text"):
                    try:
                        save_history(username, f"batch:{f['filename']}", f.get("language", "id"), result["text"], result)
                    except Exception:
                        pass

                results.append({
                    "filename": f["filename"],
                    "status": "success",
                    "data": result,
                })
            finally:
                tmp.unlink(missing_ok=True)
                tmp.with_suffix(".16k.wav").unlink(missing_ok=True)

        except Exception as exc:
            logger.exception("Batch item failed")
            results.append({
                "filename": f.get("filename", "unknown"),
                "status": "error",
                "detail": str(exc),
            })

    ok = sum(1 for r in results if r["status"] == "success")
    return {
        "status": "success",
        "summary": {"total": len(results), "ok": ok, "failed": len(results) - ok},
        "data": results,
    }


# Health check task
@celery_app.task
def health_check() -> dict:
    return {"status": "healthy", "worker": "celery"}