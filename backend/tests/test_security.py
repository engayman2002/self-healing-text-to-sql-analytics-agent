"""Tests for cryptographic security and credential handling."""

import pytest
from app.core.security import (
    DecryptionError,
    EncryptionError,
    decrypt_connection_uri,
    encrypt_connection_uri,
    generate_encryption_key,
    mask_connection_uri,
)


def test_encryption_roundtrip():
    """Verify that encrypting and decrypting a connection URI returns original plaintext."""
    key = generate_encryption_key()
    original_uri = "postgresql://dbuser:supersecret123@db.prod.internal:5432/analytics"

    token = encrypt_connection_uri(original_uri, key=key)
    assert token != original_uri
    assert isinstance(token, str)

    decrypted = decrypt_connection_uri(token, key=key)
    assert decrypted == original_uri


def test_decrypt_invalid_token_fails():
    """Verify that corrupt or invalid tokens raise DecryptionError."""
    key = generate_encryption_key()
    with pytest.raises(DecryptionError):
        decrypt_connection_uri("invalid-garbled-token", key=key)


def test_decrypt_mismatched_key_fails():
    """Verify that decrypting with the wrong key raises DecryptionError."""
    key1 = generate_encryption_key()
    key2 = generate_encryption_key()
    original_uri = "mysql://root:password@localhost:3306/mydb"

    token = encrypt_connection_uri(original_uri, key=key1)
    with pytest.raises(DecryptionError):
        decrypt_connection_uri(token, key=key2)


def test_empty_uri_encryption_fails():
    """Verify that encrypting empty strings raises EncryptionError."""
    with pytest.raises(EncryptionError):
        encrypt_connection_uri("")

    with pytest.raises(EncryptionError):
        encrypt_connection_uri("   ")


def test_mask_connection_uri():
    """Verify that passwords are masked cleanly for safe logging and UI display."""
    pg_uri = "postgresql://alice:my_secret_pass@10.0.0.5:5432/reporting_db"
    masked = mask_connection_uri(pg_uri)
    assert "my_secret_pass" not in masked
    assert "alice" in masked
    assert "reporting_db" in masked
    assert "***" in masked

    sqlite_uri = "sqlite:///relative/path/to/db.sqlite"
    assert mask_connection_uri(sqlite_uri) == sqlite_uri
