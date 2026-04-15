"""Cloud KMS encryption wrapper — encrypt/decrypt for sensitive data.

In production, uses Google Cloud KMS for envelope encryption.
In test/dev, falls back to AES-256-GCM with a local key.
"""

from __future__ import annotations

import base64
import json
import logging
import os

logger = logging.getLogger(__name__)


def _get_kms_key_name() -> str:
    """Return the full Cloud KMS crypto key resource name."""
    project = os.environ.get("GCP_PROJECT_ID", "")
    region = os.environ.get("GCP_REGION", "europe-central2")
    return (
        f"projects/{project}/locations/{region}"
        f"/keyRings/adhd-bot/cryptoKeys/oauth-tokens"
    )


def _use_local_encryption() -> bool:
    """Return True if we should use local AES encryption instead of KMS."""
    return os.environ.get("TESTING") == "1" or not os.environ.get("GCP_PROJECT_ID")


def _get_local_key() -> bytes:
    """Return local AES-256 key from env or zeroed fallback."""
    raw = os.environ.get("GOOGLE_ENCRYPTION_KEY", "")
    if raw:
        return base64.b64decode(raw)
    return b"\x00" * 32


def encrypt(plaintext: str) -> str:
    """Encrypt plaintext string.

    Uses Cloud KMS in production, local AES-256-GCM in test/dev.
    Returns a base64-encoded ciphertext string.
    """
    if _use_local_encryption():
        return _encrypt_local(plaintext)
    return _encrypt_kms(plaintext)


def decrypt(ciphertext: str) -> str:
    """Decrypt ciphertext string.

    Uses Cloud KMS in production, local AES-256-GCM in test/dev.
    Returns the original plaintext string.
    """
    if _use_local_encryption():
        return _decrypt_local(ciphertext)
    return _decrypt_kms(ciphertext)


def _encrypt_local(plaintext: str) -> str:
    """Encrypt using local AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_local_key()
    aesgcm = AESGCM(key)
    nonce = os.urandom(12)
    ct = aesgcm.encrypt(nonce, plaintext.encode(), None)
    blob = json.dumps({
        "nonce": base64.b64encode(nonce).decode(),
        "ct": base64.b64encode(ct).decode(),
    })
    return base64.b64encode(blob.encode()).decode()


def _decrypt_local(ciphertext: str) -> str:
    """Decrypt using local AES-256-GCM."""
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    key = _get_local_key()
    try:
        blob = json.loads(base64.b64decode(ciphertext).decode())
        nonce = base64.b64decode(blob["nonce"])
        ct = base64.b64decode(blob["ct"])
        aesgcm = AESGCM(key)
        return aesgcm.decrypt(nonce, ct, None).decode()
    except (KeyError, ValueError, json.JSONDecodeError):
        # Fallback: try plain base64 (migration from unencrypted)
        return base64.b64decode(ciphertext).decode()


def _encrypt_kms(plaintext: str) -> str:
    """Encrypt using Google Cloud KMS."""
    from google.cloud import kms  # type: ignore

    client = kms.KeyManagementServiceClient()
    key_name = _get_kms_key_name()

    response = client.encrypt(
        request={
            "name": key_name,
            "plaintext": plaintext.encode(),
        }
    )
    return base64.b64encode(response.ciphertext).decode()


def _decrypt_kms(ciphertext: str) -> str:
    """Decrypt using Google Cloud KMS."""
    from google.cloud import kms  # type: ignore

    client = kms.KeyManagementServiceClient()
    key_name = _get_kms_key_name()

    response = client.decrypt(
        request={
            "name": key_name,
            "ciphertext": base64.b64decode(ciphertext),
        }
    )
    return response.plaintext.decode()
