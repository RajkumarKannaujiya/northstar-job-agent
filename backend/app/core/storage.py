import base64
import hashlib
import os
from pathlib import Path
import re
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
    file_id = f"{uuid4().hex}{suffix}.enc"
    encrypted = _fernet().encrypt(content)
    if settings.storage_backend == "s3":
        _s3_client().put_object(Bucket=settings.s3_bucket, Key=file_id, Body=encrypted)
        return file_id
    root = Path(settings.storage_path).resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination = root / file_id
    destination.write_bytes(encrypted)
    try:
        os.chmod(destination, 0o600)
    except OSError:
        pass
    return file_id


def read_encrypted(file_id: str) -> bytes:
    _validate_file_id(file_id)
    if settings.storage_backend == "s3":
        response = _s3_client().get_object(Bucket=settings.s3_bucket, Key=file_id)
        return _fernet().decrypt(response["Body"].read())
    root = Path(settings.storage_path).resolve()
    path = (root / file_id).resolve()
    if path.parent != root:
        raise ValueError("Invalid storage key")
    return _fernet().decrypt(path.read_bytes())


def delete_encrypted(file_id: str) -> None:
    _validate_file_id(file_id)
    if settings.storage_backend == "s3":
        _s3_client().delete_object(Bucket=settings.s3_bucket, Key=file_id)
        return
    root = Path(settings.storage_path).resolve()
    path = (root / file_id).resolve()
    if path.parent == root and path.exists():
        path.unlink()


def _validate_file_id(file_id: str) -> None:
    if not re.fullmatch(r"[a-f0-9]{32}\.[a-z0-9]{1,8}\.enc", file_id or ""):
        raise ValueError("Invalid storage key")


def _s3_client():
    try:
        import boto3
    except ImportError as exc:
        raise RuntimeError("Install the optional boto3 dependency to use S3 storage") from exc
    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        region_name=settings.s3_region,
        aws_access_key_id=settings.s3_access_key_id,
        aws_secret_access_key=settings.s3_secret_access_key,
    )
