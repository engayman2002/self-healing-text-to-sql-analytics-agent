"""Cryptographic security utilities for sensitive database credential management."""

import logging
import re
from typing import Optional
from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.engine import make_url

from app.core.config import get_settings

logger = logging.getLogger(__name__)

# Fallback development key initialized if no key is configured in environment
_DEV_FALLBACK_KEY: Optional[bytes] = None


class SecurityError(Exception):
    """Base exception for cryptographic and security errors."""
    pass


class EncryptionError(SecurityError):
    """Raised when encrypting a credential payload fails."""
    pass


class DecryptionError(SecurityError):
    """Raised when decrypting or authenticating an encrypted token fails."""
    pass


def generate_encryption_key() -> str:
    """Generate a new cryptographically secure 32-byte Fernet key as URL-safe base64 string."""
    return Fernet.generate_key().decode("utf-8")


def _get_encryption_key(explicit_key: Optional[str] = None) -> bytes:
    """Resolve and validate the Fernet encryption key.

    Falls back to a runtime generated dev key with an explicit warning if neither
    an explicit key nor an environment ENCRYPTION_KEY is configured.
    """
    global _DEV_FALLBACK_KEY

    raw_key = explicit_key or get_settings().ENCRYPTION_KEY

    if raw_key and raw_key.strip():
        key_bytes = raw_key.strip().encode("utf-8")
        try:
            # Validate that key satisfies Fernet requirements (32 url-safe base64-encoded bytes)
            Fernet(key_bytes)
            return key_bytes
        except (ValueError, Exception) as exc:
            raise SecurityError(
                f"Invalid ENCRYPTION_KEY format: must be 32 url-safe base64-encoded bytes. Details: {exc}"
            ) from exc

    # In development or test environments where no key is provided:
    if _DEV_FALLBACK_KEY is None:
        logger.warning(
            "ENCRYPTION_KEY not configured in environment! "
            "Generating an ephemeral in-memory fallback key. "
            "Persisted credentials will NOT survive server restarts."
        )
        _DEV_FALLBACK_KEY = Fernet.generate_key()

    return _DEV_FALLBACK_KEY


def get_fernet(key: Optional[str] = None) -> Fernet:
    """Instantiate a Fernet cipher with the resolved encryption key."""
    key_bytes = _get_encryption_key(key)
    return Fernet(key_bytes)


def encrypt_connection_uri(uri: str, key: Optional[str] = None) -> str:
    """Encrypt a plaintext database connection URI using symmetric Fernet encryption.

    Args:
        uri: The plaintext connection string (e.g., 'postgresql://user:pass@host:5432/db').
        key: Optional override for the Fernet key.

    Returns:
        The URL-safe base64 encrypted ciphertext string.

    Raises:
        EncryptionError: If encryption fails or input is empty.
    """
    if not uri or not uri.strip():
        raise EncryptionError("Cannot encrypt an empty or whitespace connection URI.")

    try:
        fernet = get_fernet(key)
        encrypted_bytes = fernet.encrypt(uri.strip().encode("utf-8"))
        return encrypted_bytes.decode("utf-8")
    except Exception as exc:
        raise EncryptionError(f"Failed to encrypt connection URI: {exc}") from exc


def decrypt_connection_uri(token: str, key: Optional[str] = None) -> str:
    """Decrypt a Fernet-encrypted ciphertext string back into the raw connection URI.

    Args:
        token: The base64 Fernet token.
        key: Optional override for the Fernet key.

    Returns:
        The decrypted raw connection URI string.

    Raises:
        DecryptionError: If the token is invalid, corrupted, or tampered with.
    """
    if not token or not token.strip():
        raise DecryptionError("Cannot decrypt an empty or whitespace token.")

    try:
        fernet = get_fernet(key)
        decrypted_bytes = fernet.decrypt(token.strip().encode("utf-8"))
        return decrypted_bytes.decode("utf-8")
    except InvalidToken as exc:
        raise DecryptionError(
            "Failed to decrypt database connection URI: invalid or corrupted token, "
            "or mismatched encryption key."
        ) from exc
    except Exception as exc:
        raise DecryptionError(f"Unexpected error during credential decryption: {exc}") from exc


def mask_connection_uri(uri: str) -> str:
    """Mask credentials (passwords) in a database URI for safe logging and client display.

    E.g. 'postgresql://user:super_secret@db.host.com:5432/analytics'
      -> 'postgresql://user:***@db.host.com:5432/analytics'
    """
    if not uri:
        return ""

    try:
        url_obj = make_url(uri)
        return url_obj.render_as_string(hide_password=True)
    except Exception:
        # Fallback regex masking if URI is non-standard or sqlite file
        return re.sub(r":([^/@:]+)@", ":***@", uri)
