import base64
import os

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import (
    X25519PrivateKey,
    X25519PublicKey,
)
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from collector.ssk import WebSskExchange, extract_encrypted_ssk


def test_web_ssk_exchange_matches_x25519_aes_gcm_contract() -> None:
    server_private = X25519PrivateKey.generate()
    server_public = server_private.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    exchange = WebSskExchange(base64.b64encode(server_public).decode("ascii"))
    client_public = base64.b64decode(exchange.client_public_key_base64, validate=True)
    shared_key = server_private.exchange(X25519PublicKey.from_public_bytes(client_public))
    nonce = os.urandom(12)
    expected_ssk = os.urandom(40)
    encrypted = nonce + AESGCM(shared_key).encrypt(nonce, expected_ssk, None)

    actual = exchange.accept_encrypted_ssk(base64.b64encode(encrypted).decode("ascii"))

    assert base64.b64decode(actual) == expected_ssk


def test_extract_encrypted_ssk_accepts_observed_nesting() -> None:
    assert extract_encrypted_ssk({"loginInfo": {"ssk": "fixture"}}) == "fixture"
    assert extract_encrypted_ssk({"data": {"login_info": {"ssk": "nested"}}}) == "nested"
