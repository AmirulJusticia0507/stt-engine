"""Auth JWT + user store + history (sqlite, stdlib only kecuali PyJWT)."""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import sqlite3
import time
from pathlib import Path

import jwt

SECRET = os.getenv("JWT_SECRET", "dev-secret-ganti-di-produksi")
ALGO = "HS256"
EXP_HOURS = int(os.getenv("JWT_EXP_HOURS", "12"))

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = Path(os.getenv("STT_DB", str(BASE_DIR / "data" / "stt.db")))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


def _db() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH))
    con.row_factory = sqlite3.Row
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS users(username TEXT PRIMARY KEY, salt TEXT, pwdhash TEXT);
        CREATE TABLE IF NOT EXISTS history(id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT, at TEXT, source TEXT, lang TEXT, text TEXT);
        CREATE TABLE IF NOT EXISTS resets(token TEXT PRIMARY KEY, username TEXT, exp INTEGER);
        """
    )
    return con


def _hash(password: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000).hex()


def ensure_admin():
    user = os.getenv("ADMIN_USER", "admin")
    pwd = os.getenv("ADMIN_PASS", "admin")
    con = _db()
    row = con.execute("SELECT username FROM users WHERE username=?", (user,)).fetchone()
    if row is None:
        salt = secrets.token_hex(16)
        con.execute(
            "INSERT INTO users(username, salt, pwdhash) VALUES(?,?,?)",
            (user, salt, _hash(pwd, salt)),
        )
        con.commit()
    con.close()


def verify_user(username: str, password: str) -> bool:
    con = _db()
    row = con.execute("SELECT salt, pwdhash FROM users WHERE username=?", (username,)).fetchone()
    con.close()
    if row is None:
        return False
    return hmac.compare_digest(_hash(password, row["salt"]), row["pwdhash"])


def make_token(username: str) -> str:
    now = int(time.time())
    return jwt.encode({"sub": username, "iat": now, "exp": now + EXP_HOURS * 3600}, SECRET, algorithm=ALGO)


def parse_token(token: str) -> str | None:
    try:
        return jwt.decode(token, SECRET, algorithms=[ALGO]).get("sub")
    except Exception:
        return None


def set_password(username: str, password: str):
    con = _db()
    salt = secrets.token_hex(16)
    con.execute(
        "UPDATE users SET salt=?, pwdhash=? WHERE username=?",
        (salt, _hash(password, salt), username),
    )
    con.commit()
    con.close()


RESET_EXP_SEC = 30 * 60


def create_reset_token(username: str) -> str | None:
    con = _db()
    if con.execute("SELECT username FROM users WHERE username=?", (username,)).fetchone() is None:
        con.close()
        return None
    token = secrets.token_urlsafe(32)
    con.execute(
        "INSERT OR REPLACE INTO resets(token, username, exp) VALUES(?,?,?)",
        (token, username, int(time.time()) + RESET_EXP_SEC),
    )
    con.commit()
    con.close()
    return token


def consume_reset_token(token: str, new_password: str) -> str | None:
    con = _db()
    row = con.execute("SELECT username, exp FROM resets WHERE token=?", (token,)).fetchone()
    if row is None or row["exp"] < int(time.time()):
        con.close()
        return None
    username = row["username"]
    con.execute("DELETE FROM resets WHERE token=?", (token,))
    con.commit()
    con.close()
    set_password(username, new_password)
    return username


def save_history(username: str, source: str, lang: str, text: str):
    con = _db()
    con.execute(
        "INSERT INTO history(username, at, source, lang, text) VALUES(datetime('now'),?,?,?,?)",
        (username, source, lang, text[:2000]),
    )
    con.commit()
    con.close()


def list_history(username: str, limit: int = 50) -> list[dict]:
    con = _db()
    rows = con.execute(
        "SELECT at, source, lang, text FROM history WHERE username=? ORDER BY id DESC LIMIT ?",
        (username, limit),
    ).fetchall()
    con.close()
    return [dict(r) for r in rows]
