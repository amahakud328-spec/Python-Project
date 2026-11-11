"""Password-based document encryption using Fernet and PBKDF2."""

import base64
import hashlib
import os


class EncryptionUnavailableError(RuntimeError):
    """Raised when the optional cryptography package is not installed."""


class InvalidDocumentPasswordError(ValueError):
    """Raised when a password cannot decrypt a protected document."""


def _fernet(password: str, salt: bytes):
    try:
        from cryptography.fernet import Fernet, InvalidToken
    except ImportError as error:
        raise EncryptionUnavailableError(
            "Install the required dependency with: python -m pip install -r requirements.txt"
        ) from error
    key_material = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, 480_000, dklen=32
    )
    key = base64.urlsafe_b64encode(key_material)
    return Fernet(key), InvalidToken


def encrypt_document(content: str, password: str) -> tuple[bytes, bytes]:
    """Encrypt content and return the ciphertext and unique password salt."""
    if not password:
        raise ValueError("A non-empty password is required.")
    salt = os.urandom(16)
    fernet, _ = _fernet(password, salt)
    return fernet.encrypt(content.encode("utf-8")), salt


def decrypt_document(ciphertext: bytes, password: str, salt: bytes) -> str:
    """Decrypt content, translating authentication errors into a safe message."""
    fernet, invalid_token = _fernet(password, salt)
    try:
        return fernet.decrypt(ciphertext).decode("utf-8")
    except (invalid_token, UnicodeError) as error:
        raise InvalidDocumentPasswordError(
            "The password is incorrect or the protected document is damaged."
        ) from error
