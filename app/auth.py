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
from datetime import datetime, timedelta, timezone
from pathlib import Path

import jwt
from sqlalchemy import DateTime, Integer, String, Text, create_engine, desc, select
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

def _env_int(name: str, default: int) -> int:
    try:
        return int((os.getenv(name, "") or "").strip() or default)
    except (ValueError, TypeError):
        return default


SECRET = os.getenv("JWT_SECRET") or "dev-secret-ganti-di-produksi"
ALGO = "HS256"
EXP_HOURS = _env_int("JWT_EXP_HOURS", 12)
RESET_EXP_SEC = 30 * 60

BASE_DIR = Path(__file__).resolve().parent.parent


def database_url() -> str:
    url = os.getenv("DATABASE_URL", "").strip().strip('"').strip("'")
    if url:
        # Skema postgres:// (umum dari provider) tak dikenal SQLAlchemy;
        # normalisasi ke postgresql:// agar create_engine tidak meledak 500.
        if url.startswith("postgres://"):
            url = "postgresql://" + url[len("postgres://"):]
        return url
    legacy = os.getenv("STT_DB", "").strip()
    if legacy and not legacy.startswith("sqlite"):
        return f"sqlite:///{legacy}"
    if Path(legacy).is_absolute() if legacy else False:
        path = Path(legacy)
    elif os.getenv("VERCEL"):
        # Vercel serverless: filesystem read-only kecuali /tmp
        path = Path("/tmp/data/stt.db")
    else:
        path = Path(legacy) if legacy else BASE_DIR / "data" / "stt.db"
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except OSError:
        path = Path("/tmp/data/stt.db")
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            pass
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
    user = os.getenv("ADMIN_USER") or "admin"
    pwd = os.getenv("ADMIN_PASS") or "admin"
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
        users = s.execute(select(User).order_by(User.username)).scalars().all()
        out = []
        for u in users:
            sub = s.get(Subscription, u.username)
            plan = sub.plan if sub else "free"
            period = sub.period if sub else "monthly"
            quota = sub.quota_limit if sub else PLANS["free"]["quota"]
            out.append({
                "username": u.username,
                "role": u.role,
                "plan": plan,
                "period": period,
                "credits": u.credits,
                "quota_used": sub.quota_used if sub else 0,
                "quota_limit": quota,
            })
        return out


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


# ---- Paket langganan & billing (Midtrans) ----
# Harga placeholder (Rupiah), quota = jumlah transcribe per periode.
# quota None = unlimited.
PLANS: dict[str, dict] = {
    "community": {
        "code": "community", "name": "Community",
        "monthly": 0, "yearly": 0,
        "quota": None, "minutes": None,
        "price_per_credit": 0,
        "features": ["transcribe", "self_hosted", "open_source"],
        "self_hosted": True,
    },
    "free": {
        "code": "free", "name": "Free",
        "monthly": 0, "yearly": 0,
        "quota": 10, "minutes": 60,
        "price_per_credit": 0,
        "features": ["transcribe"],
    },
    "basic": {
        "code": "basic", "name": "Basic",
        "monthly": 49000, "yearly": 490000,
        "quota": 300, "minutes": 1800,
        "price_per_credit": 0,
        "features": ["transcribe", "batch", "export"],
    },
    "pro": {
        "code": "pro", "name": "Pro",
        "monthly": 149000, "yearly": 1490000,
        "quota": None, "minutes": None,
        "price_per_credit": 0,
        "features": ["transcribe", "batch", "async", "export", "priority"],
    },
    "payg": {
        "code": "payg", "name": "Pay-as-you-go",
        "monthly": 0, "yearly": 0,
        "quota": None, "minutes": None,
        "price_per_credit": 500,   # Rp 500 per transkripsi / kredit
        "features": ["transcribe", "batch", "export", "credits"],
        "credit_based": True,
    },
    "enterprise": {
        "code": "enterprise", "name": "Enterprise",
        "monthly": 0, "yearly": 0,   # harga custom — negosiasi
        "quota": None, "minutes": None,
        "price_per_credit": 0,
        "features": ["transcribe", "batch", "async", "export", "priority",
                     "sla", "on_premise", "dedicated_api", "custom_model"],
        "contact_only": True,
    },
}
PERIODS = ("monthly", "yearly", "onetime")
PERIOD_DAYS = {"monthly": 30, "yearly": 365, "onetime": 0}


class Subscription(Base):
    __tablename__ = "subscriptions"
    username: Mapped[str] = mapped_column(String(150), primary_key=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    period: Mapped[str] = mapped_column(String(20), default="monthly")
    status: Mapped[str] = mapped_column(String(20), default="active")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    ends_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quota_used: Mapped[int] = mapped_column(Integer, default=0)
    quota_limit: Mapped[int | None] = mapped_column(Integer, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class Payment(Base):
    __tablename__ = "payments"
    order_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    username: Mapped[str] = mapped_column(String(150), index=True)
    plan: Mapped[str] = mapped_column(String(20), default="basic")
    period: Mapped[str] = mapped_column(String(20), default="monthly")
    amount: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    raw: Mapped[str] = mapped_column(Text, default="")


def _sub_to_dict(sub: Subscription) -> dict:
    return {
        "username": sub.username,
        "plan": sub.plan,
        "period": sub.period,
        "status": sub.status,
        "started_at": sub.started_at.isoformat() if sub.started_at else None,
        "ends_at": sub.ends_at.isoformat() if sub.ends_at else None,
        "quota_used": sub.quota_used,
        "quota_limit": sub.quota_limit,
        "plan_detail": PLANS.get(sub.plan, PLANS["free"]),
    }


def get_subscription(username: str) -> dict:
    """Ambil langganan; buat Free bila belum ada; turunkan ke Free bila kedaluwarsa."""
    now = datetime.now(timezone.utc)
    with _session() as s:
        sub = s.get(Subscription, username)
        if sub is None:
            sub = Subscription(
                username=username, plan="free", period="monthly", status="active",
                started_at=now, ends_at=None, quota_used=0,
                quota_limit=PLANS["free"]["quota"], updated_at=now,
            )
            s.add(sub)
            s.commit()
        elif sub.status == "active" and sub.plan != "free" and sub.ends_at is not None:
            ends = sub.ends_at if sub.ends_at.tzinfo else sub.ends_at.replace(tzinfo=timezone.utc)
            if ends <= now:
                sub.plan = "free"
                sub.period = "monthly"
                sub.status = "expired"
                sub.quota_used = 0
                sub.quota_limit = PLANS["free"]["quota"]
                sub.ends_at = None
                sub.updated_at = now
                s.commit()
        return _sub_to_dict(sub)


def set_subscription(username: str, plan: str, period: str = "monthly") -> dict | None:
    """Aktifkan/perpanjang paket (dipakai webhook sukses & override admin)."""
    if plan not in PLANS or period not in PERIODS:
        return None
    now = datetime.now(timezone.utc)
    with _session() as s:
        if s.get(User, username) is None:
            return None
        sub = s.get(Subscription, username)
        if sub is None:
            sub = Subscription(username=username, started_at=now)
            s.add(sub)
        days = PERIOD_DAYS[period]
        base = now
        if sub.ends_at is not None:
            ends = sub.ends_at if sub.ends_at.tzinfo else sub.ends_at.replace(tzinfo=timezone.utc)
            if ends > now and sub.plan == plan:
                base = ends  # perpanjang dari sisa masa aktif
        sub.plan = plan
        sub.period = period
        sub.status = "active"
        sub.started_at = now
        sub.ends_at = None if plan == "free" else base + timedelta(days=days)
        sub.quota_used = 0
        sub.quota_limit = PLANS[plan]["quota"]
        sub.updated_at = now
        s.commit()
        return _sub_to_dict(sub)


def check_quota(username: str, n: int = 1) -> tuple[bool, dict]:
    """Admin selalu lolos. Unlimited (None) selalu lolos."""
    if is_admin_user(username):
        info = get_subscription(username)
        info["bypass"] = "admin"
        return True, info
    info = get_subscription(username)
    limit = info["quota_limit"]
    if limit is None:
        return True, info
    return (info["quota_used"] + n <= limit), info


def consume_quota(username: str, n: int = 1) -> dict:
    if is_admin_user(username):
        return get_subscription(username)
    with _session() as s:
        sub = s.get(Subscription, username)
        if sub is None:
            return get_subscription(username)
        if sub.quota_limit is not None:
            sub.quota_used += n
        sub.updated_at = datetime.now(timezone.utc)
        s.commit()
        return _sub_to_dict(sub)


def create_payment(order_id: str, username: str, plan: str, period: str, amount: int) -> dict:
    with _session() as s:
        s.merge(Payment(order_id=order_id, username=username, plan=plan,
                        period=period, amount=amount, status="pending"))
        s.commit()
        return {"order_id": order_id, "username": username, "plan": plan,
                "period": period, "amount": amount, "status": "pending"}


def update_payment(order_id: str, status: str, raw: str = "") -> dict | None:
    with _session() as s:
        row = s.get(Payment, order_id)
        if row is None:
            return None
        row.status = status
        if raw:
            row.raw = raw[:4000]
        if status in ("success", "settlement", "capture"):
            row.paid_at = datetime.now(timezone.utc)
        s.commit()
        return {"order_id": row.order_id, "username": row.username, "plan": row.plan,
                "period": row.period, "amount": row.amount, "status": row.status}


def get_payment(order_id: str) -> dict | None:
    with _session() as s:
        row = s.get(Payment, order_id)
        if row is None:
            return None
        return {"order_id": row.order_id, "username": row.username, "plan": row.plan,
                "period": row.period, "amount": row.amount, "status": row.status}


def list_payments(username: str, limit: int = 50) -> list[dict]:
    with _session() as s:
        rows = s.execute(
            select(Payment).where(Payment.username == username)
            .order_by(desc(Payment.created_at)).limit(limit)
        ).scalars().all()
        return [{"order_id": r.order_id, "plan": r.plan, "period": r.period,
                 "amount": r.amount, "status": r.status,
                 "created_at": r.created_at.isoformat() if r.created_at else None,
                 "paid_at": r.paid_at.isoformat() if r.paid_at else None} for r in rows]


def list_subscriptions() -> list[dict]:
    with _session() as s:
        rows = s.execute(select(Subscription).order_by(Subscription.username)).scalars().all()
        return [_sub_to_dict(r) for r in rows]