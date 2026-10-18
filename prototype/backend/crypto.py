"""
选票加密与凭证生成 (Ballot encryption & receipt codes)
=====================================================

诚实声明（报告里要写清楚）：
  这是**应用层对称加密**，密钥由本机 secret 派生，用于防止
  "只读数据库的人直接看到某人投了谁"。
  它 **不是** 端到端可验证加密（如 homomorphic tallying），
  也不能防御同时掌握密钥与数据库的攻击者。
  本课程项目的目标是演示分层与密钥管理，不声称达到真实选举的密码学强度。
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import uuid

_KEY_BYTES = 32


def load_or_create_secret(secret_path: str) -> bytes:
    """从文件加载密钥材料；不存在则生成。文件权限设为 0600。"""
    if os.path.exists(secret_path):
        with open(secret_path, "rb") as f:
            return f.read()
    material = secrets.token_bytes(32)
    os.makedirs(os.path.dirname(os.path.abspath(secret_path)), exist_ok=True)
    # 先以 0600 创建，再写入，避免出现短暂的可读窗口
    fd = os.open(secret_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "wb") as f:
        f.write(material)
    return material


def derive_key(master: bytes, label: str) -> bytes:
    """用 HKDF-Expand 从主密钥派生用途隔离的子密钥。"""
    return hmac.new(master, label.encode("utf-8"), hashlib.sha256).digest()[:_KEY_BYTES]


def _keystream(key: bytes, nonce: bytes, length: int) -> bytes:
    out = b""
    counter = 0
    while len(out) < length:
        out += hmac.new(key, nonce + counter.to_bytes(4, "big"), hashlib.sha256).digest()
        counter += 1
    return out[:length]


def encrypt_choice(key: bytes, choice: list[int]) -> str:
    """
    加密一个选择列表。
    格式: base64( nonce(16) || ciphertext || tag(32) )
    加密方式: keystream XOR + HMAC-SHA256 认证标签（encrypt-then-MAC）。
    """
    plaintext = ",".join(str(c) for c in choice).encode("utf-8")
    nonce = secrets.token_bytes(16)
    ct = bytes(a ^ b for a, b in zip(plaintext, _keystream(key, nonce, len(plaintext))))
    tag = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    return base64.b64encode(nonce + ct + tag).decode("ascii")


def decrypt_choice(key: bytes, blob: str) -> list[int]:
    raw = base64.b64decode(blob.encode("ascii"))
    nonce, ct, tag = raw[:16], raw[16:-32], raw[-32:]
    expected = hmac.new(key, nonce + ct, hashlib.sha256).digest()
    if not hmac.compare_digest(tag, expected):
        raise ValueError("选票密文校验失败：数据可能被篡改")
    pt = bytes(a ^ b for a, b in zip(ct, _keystream(key, nonce, len(ct))))
    text = pt.decode("utf-8")
    return [int(x) for x in text.split(",") if x != ""]


def new_anon_id() -> str:
    """与选民身份无关的随机标识。"""
    return uuid.uuid4().hex


def new_receipt_code() -> str:
    """
    给选民的凭证码。
    用 base32 大写、去掉易混字符，便于口头/手抄核对。
    """
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    groups = ["".join(secrets.choice(alphabet) for _ in range(4)) for _ in range(3)]
    return "-".join(groups)
