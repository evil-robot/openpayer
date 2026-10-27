from __future__ import annotations

import hashlib
import os
import secrets
import sqlite3
import time
from pathlib import Path

import httpx

from .config import DATA_DIR

TOKEN_TTL = 7 * 24 * 3600
SESSION_TTL = 90 * 24 * 3600
COOKIE = "openpayer_session"


def auth_enabled() -> bool:
    return bool(os.environ.get("OPENPAYER_AUTH_SECRET", ""))


def _db_path() -> Path:
    return Path(os.environ.get("OPENPAYER_AUTH_DB", str(DATA_DIR / "auth.sqlite")))


def _secret() -> str:
    return os.environ.get("OPENPAYER_AUTH_SECRET", "")


def _hash(value: str) -> str:
    return hashlib.sha256((_secret() + ":" + value).encode()).hexdigest()


def _connect() -> sqlite3.Connection:
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(str(path))
    con.execute("CREATE TABLE IF NOT EXISTS magic_tokens (token_hash TEXT PRIMARY KEY, email TEXT, expires REAL, used INTEGER DEFAULT 0)")
    con.execute("CREATE TABLE IF NOT EXISTS sessions (session_hash TEXT PRIMARY KEY, email TEXT, expires REAL)")
    return con


def allowed_domains() -> set[str]:
    return {d.strip().lower() for d in os.environ.get("OPENPAYER_ALLOWED_DOMAINS", "medtruth.care").split(",") if d.strip()}


def admin_emails() -> set[str]:
    return {e.strip().lower() for e in os.environ.get("OPENPAYER_ADMIN_EMAILS", "").split(",") if e.strip()}


def is_allowed(email: str) -> bool:
    e = email.strip().lower()
    if "@" not in e:
        return False
    if e in admin_emails():
        return True
    return e.rsplit("@", 1)[1] in allowed_domains()


def create_token(email: str) -> str:
    raw = secrets.token_urlsafe(32)
    con = _connect()
    con.execute("INSERT INTO magic_tokens VALUES (?,?,?,0)", [_hash(raw), email.strip().lower(), time.time() + TOKEN_TTL])
    con.commit()
    con.close()
    return raw


def verify_token(raw: str) -> str | None:
    """Spend a magic token once. Returns the email or None."""
    con = _connect()
    row = con.execute("SELECT email, expires, used FROM magic_tokens WHERE token_hash=?", [_hash(raw)]).fetchone()
    if not row or row[2] or row[1] < time.time():
        con.close()
        return None
    con.execute("UPDATE magic_tokens SET used=1 WHERE token_hash=?", [_hash(raw)])
    con.commit()
    con.close()
    return row[0]


def create_session(email: str) -> str:
    raw = secrets.token_urlsafe(32)
    con = _connect()
    con.execute("INSERT INTO sessions VALUES (?,?,?)", [_hash(raw), email, time.time() + SESSION_TTL])
    con.commit()
    con.close()
    return raw


def session_email(raw: str | None) -> str | None:
    if not raw:
        return None
    con = _connect()
    row = con.execute("SELECT email, expires FROM sessions WHERE session_hash=?", [_hash(raw)]).fetchone()
    con.close()
    if not row or row[1] < time.time():
        return None
    return row[0]


def delete_session(raw: str | None) -> None:
    if not raw:
        return
    con = _connect()
    con.execute("DELETE FROM sessions WHERE session_hash=?", [_hash(raw)])
    con.commit()
    con.close()


def base_url() -> str:
    return os.environ.get("OPENPAYER_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def send_sign_in_link(email: str, token: str) -> None:
    link = f"{base_url()}/confirm?token={token}"
    key = os.environ.get("RESEND_API_KEY", "")
    sender = os.environ.get("MAIL_FROM", "")
    if key and sender:
        httpx.post(
            "https://api.resend.com/emails",
            headers={"Authorization": f"Bearer {key}"},
            json={
                "from": sender,
                "to": [email],
                "subject": "Your sign-in link for OpenPayer",
                "text": f"Your sign-in link for OpenPayer:\n\n{link}\n\nIt expires in 7 days.",
            },
            timeout=20.0,
        )
    else:
        # Development only: production must set RESEND_API_KEY and MAIL_FROM.
        print(f"[openpayer dev] sign-in link for {email}: {link}")
