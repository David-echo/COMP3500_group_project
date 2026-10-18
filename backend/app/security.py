"""
安全与加密 (Security & crypto)
=============================

包含三部分：
  1. 密码哈希      —— bcrypt（不明文存储，NFR-9）
  2. JWT 签发/校验 —— python-jose
  3. 选票加密      —— AES-GCM（cryptography）

诚实声明（写进报告）：
选票加密是**应用层对称加密**，用于防止"只读数据库的人直接看到某人投了什么"。
它**不是**端到端可验证加密（如 Paillier 同态计票），
也不能防御同时掌握密钥与数据库写权限的攻击者。
本节的目标是演示密钥派生与分层，不声称达到真实选举密码学强度。
"""

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
# 密码
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
# 选票加密
# ==========================================================================

def _ballot_key() -> bytes:
    """从应用密钥派生**用途隔离**的选票子密钥（HKDF-SHA256）。"""
    hkdf = HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=None,
        info=b"election-ballot-v1",
    )
    return hkdf.derive(_settings.secret_key.encode("utf-8"))


def encrypt_choice(choice: list[int]) -> str:
    """AES-256-GCM 加密选择列表，返回 base64(nonce || ciphertext)。"""
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
    """与选民身份无关的随机标识。"""
    return secrets.token_hex(16)


def new_receipt_code() -> str:
    """便于口头核对的凭证码：3 组 4 位，去掉易混字符。"""
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)
