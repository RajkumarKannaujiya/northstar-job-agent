import base64
import hashlib
import os
from pathlib import Path
from uuid import uuid4

from cryptography.fernet import Fernet

from app.core.config import settings


def _fernet() -> Fernet:
    key = settings.file_encryption_key
    if not key:
        if settings.environment != "development":
            raise RuntimeError("FILE_ENCRYPTION_KEY must be configured outside development")
        # Local-only key. Set a unique Fernet key before storing real personal data.
        key = base64.urlsafe_b64encode(hashlib.sha256(b"job-agent-development-only-key").digest()).decode()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception as exc:
        raise RuntimeError("FILE_ENCRYPTION_KEY must be a valid Fernet key") from exc


def save_encrypted(content: bytes, suffix: str) -> str:
    root = Path(settings.storage_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    file_id = f"{uuid4().hex}{suffix}.enc"
    destination = root / file_id
    destination.write_bytes(_fernet().encrypt(content))
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return file_id


def read_encrypted(file_id: str) -> bytes:
    root = Path(settings.storage_path).resolve()
    path = (root / file_id).resolve()
    if path.parent != root:
        raise ValueError("Invalid storage key")
    return _fernet().decrypt(path.read_bytes())


def delete_encrypted(file_id: str) -> None:
    root = Path(settings.storage_path).resolve()
    path = (root / file_id).resolve()
    if path.parent == root and path.exists():
        path.unlink()
