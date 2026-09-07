import base64

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient

from app import main
from app.crypto import decrypt_secret, encrypt_secret


def test_api_requires_a_signed_in_user() -> None:
    main.app.dependency_overrides.clear()
    response = TestClient(main.app).get("/api/projects")
    assert response.status_code == 401


def test_user_api_keys_are_encrypted_and_bound_to_the_user() -> None:
    master_key = base64.urlsafe_b64encode(b"x" * 32).decode()
    ciphertext, nonce = encrypt_secret("sk-example-secret", "user-one", master_key)

    assert ciphertext != "sk-example-secret"
    assert (
        decrypt_secret(ciphertext, nonce, "user-one", master_key)
        == "sk-example-secret"
    )
    with pytest.raises(InvalidTag):
        decrypt_secret(ciphertext, nonce, "user-two", master_key)
