from __future__ import annotations

import base64
from dataclasses import dataclass, field

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


SERVER_PUBLIC_KEY_BASE64 = "Kr0iygsCu3inYJNXCL4k4JuzaYQ2afI1xbwc7BH6sm8="


def extract_encrypted_ssk(payload: dict[str, object]) -> str | None:
    paths = (
        ("ssk",),
        ("login_info", "ssk"),
        ("loginInfo", "ssk"),
        ("data", "ssk"),
        ("data", "login_info", "ssk"),
        ("data", "loginInfo", "ssk"),
    )
    for path in paths:
        value: object = payload
        for key in path:
            if not isinstance(value, dict):
                value = None
                break
            value = value.get(key)
        if isinstance(value, str) and value:
            return value
    return None


@dataclass(slots=True)
class WebSskExchange:
    server_public_key_base64: str = SERVER_PUBLIC_KEY_BASE64
    _private_key: X25519PrivateKey = field(default_factory=X25519PrivateKey.generate)

    @property
    def client_public_key_base64(self) -> str:
        raw = self._private_key.public_key().public_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PublicFormat.Raw,
        )
        return base64.b64encode(raw).decode("ascii")

    def accept_encrypted_ssk(self, value: str) -> str:
        encrypted = base64.b64decode(value, validate=True)
        server_public = base64.b64decode(self.server_public_key_base64, validate=True)
        if len(server_public) != 32:
            raise ValueError("SSK server public key must be 32 bytes")
        if len(encrypted) < 28:
            raise ValueError("Encrypted SSK is too short")
        shared_key = self._private_key.exchange(
            X25519PublicKey.from_public_bytes(server_public)
        )
        if not any(shared_key):
            raise ValueError("SSK X25519 shared key is all zero")
        decrypted = AESGCM(shared_key).decrypt(
            encrypted[:12],
            encrypted[12:],
            None,
        )
        if len(decrypted) < 32:
            raise ValueError("Decrypted SSK must be at least 32 bytes")
        return base64.b64encode(decrypted).decode("ascii")
