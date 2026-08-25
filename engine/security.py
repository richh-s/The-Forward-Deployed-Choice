"""Password hashing, session tokens, and tenant-credential encryption."""
import base64
import hashlib
import json
import secrets

import bcrypt
from cryptography.fernet import Fernet, InvalidToken

from engine.config import get_settings

# ── passwords ─────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# ── session tokens ────────────────────────────────────────────────────
# The client cookie holds a random token; the DB stores only its SHA-256,
# so a database leak does not yield usable sessions.


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── tenant credential encryption ─────────────────────────────────────
# Fernet key derived from APP_SECRET_KEY so operators manage one secret.


def _fernet() -> Fernet:
    secret = get_settings().app_secret_key
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())
    return Fernet(key)


def encrypt_credentials(payload: dict) -> str:
    return _fernet().encrypt(json.dumps(payload).encode()).decode()


def decrypt_credentials(encrypted: str) -> dict:
    try:
        return json.loads(_fernet().decrypt(encrypted.encode()))
    except (InvalidToken, ValueError) as exc:
        raise ValueError("Credential payload could not be decrypted") from exc


# ── misc ──────────────────────────────────────────────────────────────


def constant_time_equals(a: str, b: str) -> bool:
    return secrets.compare_digest(a.encode(), b.encode())
