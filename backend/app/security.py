"""Module."""
from __future__ import annotations
import base64
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any
import bcrypt
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from jose import JWTError, jwt
from .config import get_settings
_settings = get_settings()
# ==========================================================================
# ==========================================================================
def hash_password(raw: str) -> str:
    return bcrypt.hashpw(raw.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")
def verify_password(raw: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(raw.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False
# ==========================================================================
# JWT
# ==========================================================================
def create_access_token(subject: str, role: str) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=_settings.access_token_expire_minutes
    )
    payload: dict[str, Any] = {"sub": subject, "role": role, "exp": expire}
    return jwt.encode(payload, _settings.secret_key, algorithm=_settings.jwt_algorithm)
def decode_token(token: str) -> dict[str, Any] | None:
    try:
        return jwt.decode(
            token, _settings.secret_key, algorithms=[_settings.jwt_algorithm]
        )
    except JWTError:
        return None
# ==========================================================================
# ==========================================================================
def _ballot_key() -> bytes:
    """Ballot key."""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"election-ballot-v1",
    )
    return hkdf.derive(_settings.secret_key.encode("utf-8"))
def encrypt_choice(choice: list[int]) -> str:
    """Encrypt choice."""
    key = _ballot_key()
    nonce = os.urandom(12)
    plaintext = ",".join(str(c) for c in choice).encode("utf-8")
    ct = AESGCM(key).encrypt(nonce, plaintext, b"ballot")
    return base64.b64encode(nonce + ct).decode("ascii")
def decrypt_choice(blob: str) -> list[int]:
    key = _ballot_key()
    raw = base64.b64decode(blob.encode("ascii"))
    nonce, ct = raw[:12], raw[12:]
    plaintext = AESGCM(key).decrypt(nonce, ct, b"ballot").decode("utf-8")
    return [int(x) for x in plaintext.split(",") if x != ""]
def new_anon_id() -> str:
    """New anon id."""
    return secrets.token_hex(16)
def new_receipt_code() -> str:
    """New receipt code."""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)
