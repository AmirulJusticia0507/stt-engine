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


class History(Base):
    __tablename__ = "history"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    source: Mapped[str] = mapped_column(String(255), default="")
    lang: Mapped[str] = mapped_column(String(16), default="id")
    text: Mapped[str] = mapped_column(Text, default="")


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
        if s.get(User, user) is None:
            salt = secrets.token_hex(16)
            s.add(User(username=user, salt=salt, pwdhash=_hash(pwd, salt)))
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
    except Exception:
        return None


def create_reset_token(username: str) -> str | None:
    with _session() as s:
        if s.get(User, username) is None:
            return None
        token = secrets.token_urlsafe(32)
        s.merge(ResetToken(token=token, username=username, exp=int(time.time()) + RESET_EXP_SEC))
        s.commit()
        return token


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


def save_history(username: str, source: str, lang: str, text: str):
    with _session() as s:
        s.add(History(username=username, source=source, lang=lang, text=text[:2000]))
        s.commit()


def list_history(username: str, limit: int = 50) -> list[dict]:
    with _session() as s:
        rows = s.execute(
            select(History).where(History.username == username).order_by(desc(History.id)).limit(limit)
        ).scalars().all()
        out = []
        for r in rows:
            at = r.at
            out.append({
                "at": at.strftime("%Y-%m-%d %H:%M:%S") if hasattr(at, "strftime") else str(at),
                "source": r.source,
                "lang": r.lang,
                "text": r.text,
            })
        return out
