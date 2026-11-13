"""SSH key pairs Kemudi generates, and their encryption at rest.

Private keys are Fernet tokens under KEMUDI_SECRET_KEY. There is no plaintext
fallback: without a valid key, generating or using a key fails.
"""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from ..config import Settings


class SecretKeyMissing(Exception):
    """KEMUDI_SECRET_KEY is empty or not a Fernet key, or a token does not decrypt."""


MISSING_MESSAGE = "set KEMUDI_SECRET_KEY (a Fernet key) to generate or use SSH keys"


def fernet(settings: Settings) -> Fernet:
    key = (settings.secret_key or "").strip()
    if not key:
        raise SecretKeyMissing(MISSING_MESSAGE)
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as e:
        raise SecretKeyMissing(MISSING_MESSAGE) from e


def generate_keypair(comment: str = "kemudi") -> tuple[str, str, str]:
    """(private OpenSSH text, public OpenSSH line, SHA256 fingerprint)."""
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.OpenSSH,
        serialization.NoEncryption(),
    ).decode()
    public = key.public_key().public_bytes(
        serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH
    ).decode()
    if comment:
        public = f"{public} {comment}"
    return private, public, fingerprint(public)


def encrypt(settings: Settings, private: str) -> str:
    return fernet(settings).encrypt(private.encode()).decode()


def decrypt(settings: Settings, token: str) -> str:
    try:
        return fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken as e:
        raise SecretKeyMissing("stored key does not decrypt with KEMUDI_SECRET_KEY") from e


def fingerprint(public_openssh: str) -> str:
    """`SHA256:<base64 without padding>`, as `ssh-keygen -lf` prints it."""
    blob = base64.b64decode(public_openssh.split()[1])
    digest = base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip("=")
    return f"SHA256:{digest}"
