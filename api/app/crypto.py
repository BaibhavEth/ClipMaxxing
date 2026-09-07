import base64
import os

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


def _decode_master_key(encoded_key: str) -> bytes:
    try:
        key = base64.urlsafe_b64decode(encoded_key.encode())
    except (ValueError, TypeError) as exc:
        raise RuntimeError("APP_ENCRYPTION_KEY is invalid") from exc
    if len(key) != 32:
        raise RuntimeError("APP_ENCRYPTION_KEY must decode to 32 bytes")
    return key


def encrypt_secret(value: str, user_id: str, encoded_key: str) -> tuple[str, str]:
    key = _decode_master_key(encoded_key)
    nonce = os.urandom(12)
    ciphertext = AESGCM(key).encrypt(nonce, value.encode(), user_id.encode())
    return (
        base64.urlsafe_b64encode(ciphertext).decode(),
        base64.urlsafe_b64encode(nonce).decode(),
    )


def decrypt_secret(
    ciphertext: str,
    nonce: str,
    user_id: str,
    encoded_key: str,
) -> str:
    key = _decode_master_key(encoded_key)
    plaintext = AESGCM(key).decrypt(
        base64.urlsafe_b64decode(nonce.encode()),
        base64.urlsafe_b64decode(ciphertext.encode()),
        user_id.encode(),
    )
    return plaintext.decode()
