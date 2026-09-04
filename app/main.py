"""FastAPI entrypoint: REST upload + WebSocket streaming + serve frontend."""
from __future__ import annotations

import logging
import wave
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    Header,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from app.auth import (
    APIKey,
    _session,
    add_credits,
    consume_reset_token,
    create_and_send_reset_token,
    create_user,
    deduct_credits,
    delete_user,
    ensure_admin,
    export_history,
    generate_api_key,
    get_history,
    get_user_credits,
    is_admin_user,
    is_postgres as auth_db_is_postgres,
    list_audit_logs,
    list_history,
    list_users,
    log_activity,
    make_token,
    parse_token,
    save_history,
    set_user_credits,
    update_user_role,
    verify_user,
)
from app.auth import (
    is_postgres as auth_db_is_postgres,
)
from app.auth import (
    is_postgres as auth_db_is_postgres,
)
from app.celery_app import celery_app
from app.stt_engine import stt_service
from app.utils import normalize_to_wav_16k, save_upload_to_temp

# Job status storage (in production, use Redis)
job_store: dict[str, dict] = {}

ensure_admin()
bearer = HTTPBearer(auto_error=False)


def current_user(creds: HTTPAuthorizationCredentials | None = Depends(bearer), x_api_key: str | None = Header(None)) -> str | None:
    if creds is not None:
        token = parse_token(creds.credentials)
        if token:
            return token
    if x_api_key:
        row = _session().get(APIKey, x_api_key)
        if row and row.is_active:
            return row.username
    return None


def admin_user(user: str | None = Depends(current_user)) -> str:
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    if not is_admin_user(user):
        raise HTTPException(status_code=403, detail="Hanya admin")
    return user


class LoginIn(BaseModel):
    username: str
    password: str


class ForgotIn(BaseModel):
    username: str
    email: str | None = None


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
async def forgot(body: ForgotIn):
    # Selalu return success agar tidak bocor enumerasi user; token dikirim via email.
    email = body.email or body.username
    sent = await create_and_send_reset_token(body.username, email)
    return {"status": "success", "message": "Jika email terdaftar, link reset telah dikirim"}


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


@app.post("/api/v1/api-keys")
def create_api_key(user: str | None = Depends(current_user)):
    if user != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    key = generate_api_key()
    with _session() as s:
        s.add(APIKey(key=key, username="admin"))
        s.commit()
    return {"status": "success", "key": key}


@app.get("/api/v1/api-keys")
def list_api_keys(user: str | None = Depends(current_user)):
    if user != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    with _session() as s:
        rows = s.execute(select(APIKey)).scalars().all()
    return {"status": "success", "keys": [r.key for r in rows if r.is_active]}


@app.delete("/api/v1/api-keys/{key}")
def revoke_api_key(key: str, user: str | None = Depends(current_user)):
    if user != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    with _session() as s:
        row = s.get(APIKey, key)
        if row:
            row.is_active = False
            s.commit()
    return {"status": "success"}


class UserIn(BaseModel):
    username: str
    password: str
    role: str = "user"


class UserRoleIn(BaseModel):
    role: str


@app.get("/api/v1/users")
def list_users_endpoint(user: str = Depends(admin_user)):
    return {"status": "success", "users": list_users()}


@app.post("/api/v1/users")
def create_user_endpoint(body: UserIn, user: str = Depends(admin_user)):
    if not create_user(body.username, body.password, body.role):
        raise HTTPException(status_code=400, detail="Username sudah ada atau role tidak valid")
    return {"status": "success", "username": body.username, "role": body.role}


@app.patch("/api/v1/users/{username}/role")
def update_user_role_endpoint(username: str, body: UserRoleIn, user: str = Depends(admin_user)):
    if username == "admin" and body.role != "admin":
        raise HTTPException(status_code=400, detail="Tidak bisa mengubah role admin")
    if not update_user_role(username, body.role):
        raise HTTPException(status_code=400, detail="User tidak ditemukan atau role tidak valid")
    return {"status": "success", "username": username, "role": body.role}


@app.delete("/api/v1/users/{username}")
def delete_user_endpoint(username: str, user: str = Depends(admin_user)):
    if username == "admin":
        raise HTTPException(status_code=400, detail="Tidak bisa menghapus admin")
    if not delete_user(username):
        raise HTTPException(status_code=400, detail="User tidak ditemukan")
    return {"status": "success"}


class CreditsTopupIn(BaseModel):
    username: str
    amount: int


class CreditsDeductIn(BaseModel):
    username: str
    amount: int


class CreditsSetIn(BaseModel):
    username: str
    amount: int


@app.get("/api/v1/users/{username}/credits")
def get_credits_endpoint(username: str, user: str = Depends(admin_user)):
    credits = get_user_credits(username)
    return {"status": "success", "username": username, "credits": credits}


@app.post("/api/v1/users/{username}/credits/topup")
def topup_credits_endpoint(username: str, body: CreditsTopupIn, user: str = Depends(admin_user)):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount harus > 0")
    new_credits = add_credits(username, body.amount)
    return {"status": "success", "username": username, "credits": new_credits}


@app.post("/api/v1/users/{username}/credits/deduct")
def deduct_credits_endpoint(username: str, body: CreditsDeductIn, user: str = Depends(admin_user)):
    if body.amount <= 0:
        raise HTTPException(status_code=400, detail="Amount harus > 0")
    success, remaining = deduct_credits(username, body.amount)
    if not success:
        raise HTTPException(status_code=400, detail="Kredit tidak cukup atau user tidak ditemukan")
    return {"status": "success", "username": username, "credits": remaining}


@app.post("/api/v1/users/{username}/credits/set")
def set_credits_endpoint(username: str, body: CreditsSetIn, user: str = Depends(admin_user)):
    if body.amount < 0:
        raise HTTPException(status_code=400, detail="Amount tidak boleh negatif")
    if not set_user_credits(username, body.amount):
        raise HTTPException(status_code=400, detail="User tidak ditemukan")
    return {"status": "success", "username": username, "credits": body.amount}


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
        result = stt_service.switch_model(body.model)
        log_activity(user, 'model_switch', f'model:{body.model}')
        return {"status": "success", "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.get("/api/v1/history")
def history(user: str | None = Depends(current_user)):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    return {"status": "success", "data": list_history(user)}


@app.get("/api/v1/audit/log")
def audit_log(user: str | None = Depends(current_user), limit: int = 50):
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    return {"status": "success", "data": list_audit_logs(user, limit)}


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
    log_activity(user, 'export', f'format:{format},item:{item_id}')
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
    # Check credits (1 credit per transcribe)
    if user:
        success, remaining = deduct_credits(user, 1)
        if not success:
            raise HTTPException(status_code=402, detail=f"Kredit tidak cukup. Sisa: {remaining}")
    raw = await file.read()
    out = _transcribe_bytes(file.filename or "audio.wav", raw, language, user)
    if user:
        log_activity(user, 'transcribe', f'file:{file.filename or "audio.wav"}')
    if out["status"] == "error":
        code = 503 if "belum terinstall" in out.get("detail", "") else 400
        raise HTTPException(status_code=code, detail=out["detail"])
    return {"status": "success", "data": out["data"], "credits_remaining": remaining if user else None}


@app.post("/api/v1/transcribe-batch")
async def transcribe_batch(
    files: list[UploadFile] = File(...),
    language: str = "id",
    user: str | None = Depends(current_user),
):
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maksimal 20 file per batch")
    # Check credits (1 credit per file)
    if user:
        success, remaining = deduct_credits(user, len(files))
        if not success:
            raise HTTPException(status_code=402, detail=f"Kredit tidak cukup untuk {len(files)} file. Sisa: {remaining}")
    results = []
    for f in files:
        raw = await f.read()
        results.append(_transcribe_bytes(f.filename or "audio.wav", raw, language, user, "batch"))
        if user:
            log_activity(user, 'transcribe', f'batch:{f.filename or "audio.wav"}')
    ok = sum(1 for r in results if r["status"] == "success")
    return {"status": "success", "summary": {"total": len(results), "ok": ok, "failed": len(results) - ok}, "data": results, "credits_remaining": remaining if user else None}


# Async transcription endpoints (Celery)
import base64


@app.post("/api/v1/transcribe-async")
async def transcribe_async(
    file: UploadFile = File(...),
    language: str = "id",
    user: str | None = Depends(current_user),
):
    """Submit transcription job to Celery queue."""
    # Check credits (1 credit per transcribe)
    if user:
        success, remaining = deduct_credits(user, 1)
        if not success:
            raise HTTPException(status_code=402, detail=f"Kredit tidak cukup. Sisa: {remaining}")
    raw = await file.read()
    file_b64 = base64.b64encode(raw).decode()

    task = celery_app.send_task(
        "app.tasks.transcribe_file_task",
        args=[file_b64, file.filename or "audio.wav", language, user, "upload"],
    )
    job_store[task.id] = {"status": "PENDING", "type": "transcribe", "filename": file.filename}
    if user:
        log_activity(user, 'transcribe_async', f'file:{file.filename or "audio.wav"}')
    return {"status": "success", "task_id": task.id, "message": "Job queued", "credits_remaining": remaining}


@app.post("/api/v1/transcribe-batch-async")
async def transcribe_batch_async(
    files: list[UploadFile] = File(...),
    language: str = "id",
    user: str | None = Depends(current_user),
):
    """Submit batch transcription job to Celery queue."""
    if len(files) > 20:
        raise HTTPException(status_code=400, detail="Maksimal 20 file per batch")
    # Check credits (1 credit per file)
    if user:
        success, remaining = deduct_credits(user, len(files))
        if not success:
            raise HTTPException(status_code=402, detail=f"Kredit tidak cukup untuk {len(files)} file. Sisa: {remaining}")

    files_data = []
    for f in files:
        raw = await f.read()
        files_data.append({
            "filename": f.filename or "audio.wav",
            "data_b64": base64.b64encode(raw).decode(),
            "language": language,
        })

    task = celery_app.send_task(
        "app.tasks.transcribe_batch_task",
        args=[files_data, user],
    )
    job_store[task.id] = {"status": "PENDING", "type": "batch", "count": len(files)}
    if user:
        log_activity(user, 'transcribe_batch_async', f'count:{len(files)}')
    return {"status": "success", "task_id": task.id, "message": "Batch job queued", "credits_remaining": remaining}


@app.get("/api/v1/jobs/{task_id}")
def get_job_status(task_id: str, user: str | None = Depends(current_user)):
    """Get Celery job status."""
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")

    # Check local store first
    if task_id in job_store:
        job_info = job_store[task_id].copy()
    else:
        job_info = {}

    # Get actual Celery result
    result = celery_app.AsyncResult(task_id)
    job_info.update({
        "task_id": task_id,
        "status": result.state,
        "result": result.result if result.ready() else None,
    })

    # Update local store
    job_store[task_id] = job_info
    return {"status": "success", "data": job_info}


@app.get("/api/v1/jobs")
def list_jobs(user: str | None = Depends(current_user)):
    """List all jobs for current user."""
    if user is None:
        raise HTTPException(status_code=401, detail="Butuh token")
    # Return jobs from store (in production, filter by user)
    return {"status": "success", "jobs": job_store}


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
