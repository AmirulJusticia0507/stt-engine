"""Auth JWT + user/history store di atas SQLAlchemy dual-DB.

- Default (testing/lokal): SQLite file via ``DATABASE_URL`` kosong
  -> ``sqlite:///./data/stt.db`` (nol setup).
- Data beneran (produksi): set ``DATABASE_URL=postgresql+psycopg://user:pass@host:5432/stt``
  -> butuh server Postgres + ``pip install -r requirements.txt`` (ada psycopg).

Kompatibel mundur: env lama ``STT_DB=/path/ke.db`` tetap dibaca sebagai SQLite.
API publik tidak berubah sehingga ``app/main.py`` tidak perlu diubah.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path

import jwt
from sqlalchemy import DateTime, Integer, String, Text, create_engine, desc, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

SECRET = os.getenv("JWT_SECRET", "dev-secret-ganti-di-produksi")
ALGO = "HS256"
EXP_HOURS = int(os.getenv("JWT_EXP_HOURS", "12"))
RESET_EXP_SEC = 30 * 60

BASE_DIR = Path(__file__).resolve().parent.parent


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip()
    if url:
        return url
    legacy = os.getenv("STT_DB", "").strip()
    if legacy and not legacy.startswith("sqlite"):
        return f"sqlite:///{legacy}"
    path = Path(legacy) if legacy else BASE_DIR / "data" / "stt.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    return f"sqlite:///{path}"


def is_postgres(url: str = "") -> bool:
    return (url or database_url()).startswith("postgresql")


_engine = None


def get_engine():
    global _engine
    if _engine is None:
        url = database_url()
        kwargs: dict = {"pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)
        Base.metadata.create_all(_engine)
        with _engine.begin() as conn:  # migrasi ringan DB lama -> kolom data, role & credits
            try:
                if _engine.dialect.name == "sqlite":
                    cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(history)").fetchall()]
                    if "data" not in cols:
                        conn.exec_driver_sql("ALTER TABLE history ADD COLUMN data TEXT DEFAULT '{}'")
                    user_cols = [r[1] for r in conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()]
                    if "role" not in user_cols:
                        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'user'")
                    if "credits" not in user_cols:
                        conn.exec_driver_sql("ALTER TABLE users ADD COLUMN credits INTEGER DEFAULT 0")
                else:
                    conn.exec_driver_sql("ALTER TABLE history ADD COLUMN IF NOT EXISTS data TEXT DEFAULT '{}'")
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS role TEXT DEFAULT 'user'")
                    conn.exec_driver_sql("ALTER TABLE users ADD COLUMN IF NOT EXISTS credits INTEGER DEFAULT 0")
            except (Exception, OSError):
                pass  # Migration may fail on old DBs, that's OK
    return _engine


def reset_engine():  # dipakai saat DATABASE_URL berubah (mis. tes)
    global _engine
    if _engine is not None:
        _engine.dispose()
    _engine = None


def _session() -> Session:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)()


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(150), primary_key=True)
    salt: Mapped[str] = mapped_column(String(64))
    pwdhash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(20), default="user")
    credits: Mapped[int] = mapped_column(Integer, default=0)


class History(Base):
    __tablename__ = "history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    source: Mapped[str] = mapped_column(String(255), default="")
    lang: Mapped[str] = mapped_column(String(16), default="id")
    text: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[str] = mapped_column(Text, default="{}")  # JSON penuh (segments) untuk ekspor SRT/VTT


class ResetToken(Base):
    __tablename__ = "resets"
    token: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    exp: Mapped[int] = mapped_column(Integer)


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def ensure_admin():
    user = os.getenv("ADMIN_USER", "admin")
    pwd = os.getenv("ADMIN_PASS", "admin")
    with _session() as s:
        existing = s.get(User, user)
        if existing is None:
            salt = secrets.token_hex(16)
            s.add(User(username=user, salt=salt, pwdhash=_hash(pwd, salt), role="admin"))
            s.commit()
        elif existing.role != "admin":
            existing.role = "admin"
            s.commit()


def verify_user(username: str, password: str) -> bool:
    with _session() as s:
        row = s.get(User, username)
        if row is None:
            return False
        return hmac.compare_digest(_hash(password, row.salt), row.pwdhash)


def set_password(username: str, password: str):
    with _session() as s:
        row = s.get(User, username)
        if row is None:
            return
        row.salt = secrets.token_hex(16)
        row.pwdhash = _hash(password, row.salt)
        s.commit()


def make_token(username: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": username, "iat": now, "exp": now + EXP_HOURS * 3600}, SECRET, algorithm=ALGO)


def parse_token(token: str) -> str | None:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO]).get("sub")
    except jwt.PyJWTError:
        return None


def create_reset_token(username: str) -> str | None:
    with _session() as s:
        if s.get(User, username) is None:
            return None
        token = secrets.token_urlsafe(32)
        s.merge(ResetToken(token=token, username=username, exp=int(time.time()) + RESET_EXP_SEC))
        s.commit()
        return token


async def create_and_send_reset_token(username: str, email: str) -> bool:
    """
    Create reset token and send email.
    Returns True if email sent (or SMTP not configured), False on error.
    """
    token = create_reset_token(username)
    if not token:
        return False
    try:
        from app.email_utils import send_reset_email
        return await send_reset_email(email, username, token)
    except Exception:
        return False


def consume_reset_token(token: str, new_password: str) -> str | None:
    with _session() as s:
        row = s.get(ResetToken, token)
        if row is None or row.exp < int(time.time()):
            return None
        username = row.username
        s.delete(row)
        s.commit()
    set_password(username, new_password)
    return username


def save_history(username: str, source: str, lang: str, text: str, data: dict | None = None):
    with _session() as s:
        s.add(History(
            username=username, source=source, lang=lang, text=text[:2000],
            data=json.dumps(data or {}, default=str)[:200000],
        ))
        s.commit()


def get_history(item_id: int, username: str) -> dict | None:
    with _session() as s:
        r = s.get(History, item_id)
        if r is None or r.username != username:
            return None
        try:
            data = json.loads(r.data or "{}")
        except Exception:
            data = {}
        return {"id": r.id, "source": r.source, "lang": r.lang, "text": r.text, "data": data}


def _ts(sec: float, sep: str) -> str:
    ms = int(round(float(sec) * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02}{sep}{ms:03}"


def export_history(item: dict, fmt: str) -> tuple[str, str, str]:
    """Return (content, media_type, filename). fmt: txt|srt|vtt."""
    fmt = (fmt or "txt").lower()
    text = item.get("text", "")
    segs = (item.get("data") or {}).get("segments") or []
    base = f"transkrip-{item.get('id', 0)}"
    if fmt == "srt":
        lines = []
        for i, sg in enumerate(segs, 1):
            lines.append(f"{i}\n{_ts(sg.get('start', 0), ',')} --> {_ts(sg.get('end', 0), ',')}\n{sg.get('text', '').strip()}\n")
        body = "\n".join(lines) if lines else text
        return body + "\n", "application/x-subrip", f"{base}.srt"
    if fmt == "vtt":
        lines = ["WEBVTT\n"]
        for sg in segs:
            lines.append(f"{_ts(sg.get('start', 0), '.')} --> {_ts(sg.get('end', 0), '.')}\n{sg.get('text', '').strip()}\n")
        body = "\n".join(lines) if len(lines) > 1 else "WEBVTT\n\n" + text + "\n"
        return body, "text/vtt", f"{base}.vtt"
    return text + "\n", "text/plain; charset=utf-8", f"{base}.txt"


def list_history(username: str, limit: int = 50) -> list[dict]:
    with _session() as s:
        rows = s.execute(
            select(History).where(History.username == username).order_by(desc(History.id)).limit(limit)
        ).scalars().all()
        out = []
        for r in rows:
            at = r.at
            out.append({
                "id": r.id,
                "at": at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(at, "strftime") else str(at),
                "source": r.source,
                "lang": r.lang,
                "text": r.text,
            })
        return out


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    action: Mapped[str] = mapped_column(String(100), default="")
    detail: Mapped[str] = mapped_column(Text, default="")


def log_activity(username: str, action: str, detail: str = ""):
    with _session() as s:
        s.add(AuditLog(username=username, action=action, detail=detail[:2000]))
        s.commit()


class APIKey(Base):
    __tablename__ = "api_keys"
    key: Mapped[str] = mapped_column(String(128), unique=True, index=True, primary_key=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


def generate_api_key() -> str:
    return secrets.token_urlsafe(32)


def list_audit_logs(username: str, limit: int = 50) -> list[dict]:
    with _session() as s:
        rows = s.execute(
            select(AuditLog).where(AuditLog.username == username).order_by(desc(AuditLog.id)).limit(limit)
        ).scalars().all()
        out = []
        for r in rows:
            at = r.at
            out.append({
                "id": r.id,
                "at": at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(at, "strftime") else str(at),
                "action": r.action,
                "detail": r.detail,
            })
        return out


def get_user_role(username: str) -> str | None:
    with _session() as s:
        user = s.get(User, username)
        return user.role if user else None


def is_admin_user(username: str) -> bool:
    return get_user_role(username) == "admin"


def list_users() -> list[dict]:
    with _session() as s:
        rows = s.execute(select(User).order_by(User.username)).scalars().all()
        return [{"username": r.username, "role": r.role} for r in rows]


def create_user(username: str, password: str, role: str = "user") -> bool:
    if role not in ("user", "admin"):
        return False
    with _session() as s:
        if s.get(User, username) is not None:
            return False
        salt = secrets.token_hex(16)
        s.add(User(username=username, salt=salt, pwdhash=_hash(password, salt), role=role))
        s.commit()
    return True


def update_user_role(username: str, role: str) -> bool:
    if role not in ("user", "admin"):
        return False
    with _session() as s:
        user = s.get(User, username)
        if user is None:
            return False
        user.role = role
        s.commit()
    return True


def delete_user(username: str) -> bool:
    with _session() as s:
        user = s.get(User, username)
        if user is None:
            return False
        s.delete(user)
        s.commit()
    return True


def get_user_credits(username: str) -> int:
    with _session() as s:
        user = s.get(User, username)
        return user.credits if user else 0


def add_credits(username: str, amount: int) -> int:
    if amount <= 0:
        return 0
    with _session() as s:
        user = s.get(User, username)
        if user is None:
            return 0
        user.credits += amount
        s.commit()
        return user.credits


def deduct_credits(username: str, amount: int) -> tuple[bool, int]:
    """Deduct credits. Returns (success, remaining_credits)."""
    if amount <= 0:
        return False, 0
    with _session() as s:
        user = s.get(User, username)
        if user is None or user.credits < amount:
            return False, user.credits if user else 0
        user.credits -= amount
        s.commit()
        return True, user.credits


def set_user_credits(username: str, amount: int) -> bool:
    if amount < 0:
        return False
    with _session() as s:
        user = s.get(User, username)
        if user is None:
            return False
        user.credits = amount
        s.commit()
        return True