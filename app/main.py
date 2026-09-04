"""FastAPI entrypoint: REST upload + WebSocket streaming + serve frontend."""
from __future__ import annotations

import logging
import wave
from pathlib import Path

from fastapi import Depends, FastAPI, File, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.auth import (
    consume_reset_token,
    create_reset_token,
    ensure_admin,
    export_history,
    get_history,
    is_postgres as auth_db_is_postgres,
    list_history,
    make_token,
    parse_token,
    save_history,
    verify_user,
)
from app.stt_engine import stt_service
from app.utils import normalize_to_wav_16k, save_upload_to_temp

ensure_admin()
bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer)) -> str | None:
    if creds is None:
        return None
    return parse_token(creds.credentials)


class LoginIn(BaseModel):
    username: str
    password: str


class ForgotIn(BaseModel):
    username: str


class ResetIn(BaseModel):
    token: str
    new_password: str

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("stt-engine")

app = FastAPI(
    title="Voice-to-Text Engine API",
    description="High-performance Speech-to-Text REST & WebSocket API (FastAPI + Faster-Whisper)",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # ketat-kan di produksi
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent.parent
FRONTEND_DIR = BASE_DIR / "frontend"


@app.get("/health")
def health_check():
    return {"status": "ok", **stt_service.status}


@app.post("/api/v1/auth/login")
def login(body: LoginIn):
    if not verify_user(body.username, body.password):
        raise HTTPException(status_code=401, detail="Kredensial salah")
    return {"access_token": make_token(body.username), "token_type": "bearer"}


@app.post("/api/v1/auth/forgot")
def forgot(body: ForgotIn):
    # Selalu return success agar tidak bocor enumerasi user; token dikembalikan di dev.
    token = create_reset_token(body.username)
    return {"status": "success", "reset_token": token}


@app.post("/api/v1/auth/reset")
def reset(body: ResetIn):
    if len(body.new_password) < 4:
        raise HTTPException(status_code=400, detail="Password minimal 4 karakter")
    user = consume_reset_token(body.token, body.new_password)
    if user is None:
        raise HTTPException(status_code=400, detail="Token reset tidak valid / kedaluwarsa")
    return {"status": "success", "username": user}


@app.get("/api/v1/me")
def me(user: str | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    return {"username": user}


def system_info() -> dict:
    import shutil

    info: dict = {**stt_service.status}
    try:
        import torch

        info["torch"] = torch.__version__
        info["cuda_available"] = torch.cuda.is_available()
        if torch.cuda.is_available():
            info["gpu_name"] = torch.cuda.get_device_name(0)
            free, total = torch.cuda.mem_get_info(0)
            info["vram_free_mb"] = round(free / 1024**2)
            info["vram_total_mb"] = round(total / 1024**2)
    except ImportError:
        info["torch"] = None
        info["cuda_available"] = False
    try:
        import faster_whisper

        info["faster_whisper"] = faster_whisper.__version__
    except Exception:
        info["faster_whisper"] = None
    info["ffmpeg"] = shutil.which("ffmpeg") is not None
    info["db"] = "postgres" if auth_db_is_postgres() else "sqlite"
    return info


@app.get("/api/v1/system")
def system(user: str | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    return {"status": "success", "data": system_info()}


class ModelIn(BaseModel):
    model: str


@app.post("/api/v1/system/model")
def set_model(body: ModelIn, user: str | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    try:
        return {"status": "success", "data": stt_service.switch_model(body.model)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/history")
def history(user: str | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    return {"status": "success", "data": list_history(user)}


@app.get("/api/v1/history/{item_id}/export")
def export_item(item_id: int, format: str = "txt", user: str | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    if format.lower() not in ("txt", "srt", "vtt"):
        raise HTTPException(status_code=400, detail="Format harus txt|srt|vtt")
    item = get_history(item_id, user)
    if item is None:
        raise HTTPException(status_code=404, detail="Riwayat tidak ditemukan")
    body, media, filename = export_history(item, format)
    return Response(content=body.encode("utf-8"), media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


ALLOWED_AUDIO = (".wav", ".mp3", ".m4a", ".ogg", ".flac", ".webm")


def _transcribe_bytes(filename: str, raw: bytes, language: str, user: str | None, source_prefix: str = "upload") -> dict:
    suffix = Path(filename or "audio.wav").suffix or ".wav"
    if suffix.lower() not in ALLOWED_AUDIO:
        return {"filename": filename, "status": "error", "detail": f"Format {suffix} tidak didukung"}
    if not raw:
        return {"filename": filename, "status": "error", "detail": "File kosong"}
    tmp = save_upload_to_temp(raw, suffix)
    try:
        result = stt_service.transcribe_file(tmp, language=language)
        if user and result.get("text"):
            try:
                save_history(user, f"{source_prefix}:{filename}", language, result["text"], result)
            except Exception:
                pass
        return {"filename": filename, "status": "success", "data": result}
    except RuntimeError as e:
        return {"filename": filename, "status": "error", "detail": str(e)}
    except Exception as e:
        logger.exception("transcribe failed")
        return {"filename": filename, "status": "error", "detail": str(e)}
    finally:
        tmp.unlink(missing_ok=True)
        tmp.with_suffix(".16k.wav").unlink(missing_ok=True)


@app.post("/api/v1/transcribe")
async def transcribe_audio(
    file: UploadFile = File(...),
    language: str = "id",
    user: str | None = Depends(current_user),
):
    raw = await file.read()
    out = _transcribe_bytes(file.filename or "audio.wav", raw, language, user)
    if out["status"] == "error":
        code = 503 if "belum terinstall" in out.get("detail", "") else 400
        raise HTTPException(status_code=code, detail=out["detail"])
    return {"status": "success", "data": out["data"]}


@app.post("/api/v1/transcribe-batch")
async def transcribe_batch(
    files: list[UploadFile] = File(...),
    language: str = "id",
    user: str | None = Depends(current_user),
):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maksimal 20 file per batch")
    results = []
    for f in files:
        raw = await f.read()
        results.append(_transcribe_bytes(f.filename or "audio.wav", raw, language, user, "batch"))
    ok = sum(1 for r in results if r["status"] == "success")
    return {"status": "success", "summary": {"total": len(results), "ok": ok, "failed": len(results) - ok}, "data": results}


@app.websocket("/ws/v1/transcribe-stream")
async def websocket_transcribe(websocket: WebSocket, language: str = "id", token: str | None = None):
    """Terima PCM 16-bit 16kHz mono (bytes), buffer ~1.5 dtk, lalu transcribe."""
    await websocket.accept()
    ws_user = parse_token(token) if token else None
    # 16000 sample/dtk * 2 byte * 1.5 dtk = 48000 byte
    min_bytes = 48000
    buffer = bytearray()
    try:
        while True:
            chunk = await websocket.receive_bytes()
            buffer.extend(chunk)
            await websocket.send_json({"event": "chunk_received", "bytes_length": len(chunk)})

            if len(buffer) < min_bytes:
                continue

            pcm = bytes(buffer)
            buffer.clear()
            try:
                wav_path = _pcm_to_wav_file(pcm)
                try:
                    norm = normalize_to_wav_16k(wav_path)
                    result = stt_service.transcribe_file(norm, language=language)
                    if ws_user and result.get("text"):
                        try:
                            save_history(ws_user, "mic-stream", language, result["text"], result)
                        except Exception:
                            pass
                    await websocket.send_json({"event": "transcript", "data": result})
                finally:
                    wav_path.unlink(missing_ok=True)
            except RuntimeError as e:
                await websocket.send_json({"event": "error", "detail": str(e)})
            except Exception as e:
                await websocket.send_json({"event": "error", "detail": str(e)})
    except WebSocketDisconnect:
        logger.info("WS client disconnected")


def _pcm_to_wav_file(pcm: bytes, sample_rate: int = 16000) -> Path:
    tmp = save_upload_to_temp(b"", ".wav")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sample_rate)
        w.writeframes(pcm)
    return tmp


# Serve frontend Vue (single-file) di root "/" jika ada
if FRONTEND_DIR.exists():
    index = FRONTEND_DIR / "index.html"
    if index.exists():

        @app.get("/", include_in_schema=False)
        def serve_index():
            return FileResponse(str(index))

    app.mount("/frontend", StaticFiles(directory=str(FRONTEND_DIR), html=True), name="frontend")
