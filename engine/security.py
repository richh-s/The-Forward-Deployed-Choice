"""Password hashing, session tokens, CSRF tokens, and tenant-credential
encryption."""
import asyncio
import base64
import hashlib
import hmac
import json
import secrets

import bcrypt
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from engine.config import get_settings

# ── passwords ─────────────────────────────────────────────────────────


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


# bcrypt takes ~100ms of CPU — never run it on the event loop.


async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(password: str, password_hash: str) -> bool:
    return await asyncio.to_thread(verify_password, password, password_hash)


# A real (but throwaway) hash so login timing is identical whether or not
# the email resolves to a user.
_DUMMY_HASH = bcrypt.hashpw(b"timing-equalizer", bcrypt.gensalt()).decode()


async def equalize_verify_timing() -> None:
    await asyncio.to_thread(verify_password, "wrong-password", _DUMMY_HASH)


# ── session tokens ────────────────────────────────────────────────────
# The client cookie holds a random token; the DB stores only its SHA-256,
# so a database leak does not yield usable sessions.


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def hash_session_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


# ── CSRF tokens ───────────────────────────────────────────────────────
# Stateless per-session token: HMAC(app secret, session token). The form
# field must match the value recomputed from the session cookie, which a
# cross-site attacker can neither read nor predict.


def csrf_token_for(session_token: str) -> str:
    key = get_settings().app_secret_key.encode()
    return hmac.new(key, b"csrf:" + session_token.encode(), hashlib.sha256).hexdigest()


def verify_csrf_token(session_token: str, presented: str) -> bool:
    if not presented:
        return False
    return hmac.compare_digest(csrf_token_for(session_token), presented)


# ── tenant credential encryption ─────────────────────────────────────
# Fernet key derived from APP_SECRET_KEY via HKDF with domain separation.
# APP_SECRET_KEY_OLD (if set) is accepted for decryption during rotation;
# writes always use the current key.


def _derive_key(secret: str) -> bytes:
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"engine.credentials.v1",
        info=b"workspace-credential-encryption",
    )
    return base64.urlsafe_b64encode(hkdf.derive(secret.encode()))


def _legacy_key(secret: str) -> bytes:
    # Pre-HKDF derivation, kept for decrypting existing rows.
    return base64.urlsafe_b64encode(hashlib.sha256(secret.encode()).digest())


def _fernet() -> MultiFernet:
    settings = get_settings()
    keys = [Fernet(_derive_key(settings.app_secret_key))]
    keys.append(Fernet(_legacy_key(settings.app_secret_key)))
    if settings.app_secret_key_old:
        keys.append(Fernet(_derive_key(settings.app_secret_key_old)))
        keys.append(Fernet(_legacy_key(settings.app_secret_key_old)))
    return MultiFernet(keys)


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
