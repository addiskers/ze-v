"""
EO Admin auth: scrypt password hashing + a small signed bearer token (HMAC, no
extra deps). The React SPA logs in, stores the token, and sends it as
`Authorization: Bearer <token>`. Separate from the Super-Admin shared-secret path.
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from fastapi import HTTPException, Request

import eo_db

logger = logging.getLogger(__name__)

_SESSION_SECRET = (os.getenv("EO_SESSION_SECRET") or os.getenv("ANALYTICS_SECRET") or "eo-dev-secret").encode()
_TOKEN_TTL = int(os.getenv("EO_SESSION_TTL", str(60 * 60 * 24 * 14)))  # 14 days

_SCRYPT = dict(n=16384, r=8, p=1, dklen=32)


# ── password hashing ─────────────────────────────────────────────────────────
def hash_password(password: str, salt_hex: str | None = None) -> tuple[str, str]:
    salt = bytes.fromhex(salt_hex) if salt_hex else secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, **_SCRYPT)
    return dk.hex(), salt.hex()


def verify_password(password: str, hash_hex: str, salt_hex: str) -> bool:
    try:
        expected = bytes.fromhex(hash_hex)
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), **_SCRYPT)
        return hmac.compare_digest(dk, expected)
    except Exception:
        return False


# ── signed token ─────────────────────────────────────────────────────────────
def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _unb64(s: str) -> bytes:
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def issue_token(user: dict) -> str:
    payload = {"uid": user["id"], "role": user["role"], "exp": int(time.time()) + _TOKEN_TTL}
    body = _b64(json.dumps(payload, separators=(",", ":")).encode())
    sig = _b64(hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).digest())
    return f"{body}.{sig}"


def verify_token(token: str) -> dict | None:
    try:
        body, sig = token.split(".", 1)
        expected = _b64(hmac.new(_SESSION_SECRET, body.encode(), hashlib.sha256).digest())
        if not hmac.compare_digest(sig, expected):
            return None
        payload = json.loads(_unb64(body))
        if int(payload.get("exp", 0)) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


# ── seed + login ─────────────────────────────────────────────────────────────
def seed_admin() -> None:
    """Create the first eo_admin from env if the users table is empty."""
    if eo_db.count_users() > 0:
        return
    username = os.getenv("EO_ADMIN_USER", "eoadmin")
    password = os.getenv("EO_ADMIN_PASS", "eoadmin123")
    h, s = hash_password(password)
    eo_db.create_user(username=username, name="EO Admin", password_hash=h, password_salt=s, role="eo_admin")
    logger.info("Seeded initial EO admin user '%s'", username)


def authenticate(username: str, password: str) -> dict | None:
    user = eo_db.get_user_by_username(username)
    if not user or not user.get("active"):
        # constant-ish time: still run a hash to blunt username enumeration
        hash_password(password)
        return None
    if not verify_password(password, user["password_hash"], user["password_salt"]):
        return None
    return user


# ── FastAPI dependencies ─────────────────────────────────────────────────────
def _token_from_request(request: Request) -> str:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    # cookie or ?token= (the latter lets an <audio>/<a> element authenticate, since
    # those can't send an Authorization header — used for streaming call recordings).
    return request.cookies.get("eo_session", "") or request.query_params.get("token", "")


def require_eo(request: Request) -> dict:
    """Any authenticated EO user (eo_admin or eo_agent)."""
    payload = verify_token(_token_from_request(request))
    if not payload:
        raise HTTPException(status_code=401, detail="Not authenticated")
    user = eo_db.get_user(int(payload["uid"]))
    if not user or not user.get("active"):
        raise HTTPException(status_code=401, detail="Not authenticated")
    return user


def require_eo_admin(request: Request) -> dict:
    """EO users with the manager role (Users/Settings)."""
    user = require_eo(request)
    if user.get("role") != "eo_admin":
        raise HTTPException(status_code=403, detail="Admin role required")
    return user
