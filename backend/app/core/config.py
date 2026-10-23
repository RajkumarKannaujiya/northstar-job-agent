from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Job Agent"
    environment: str = "development"
    database_url: str = "sqlite:///./job_agent.db"
    redis_url: str = "redis://redis:6379/0"
    jwt_secret_key: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    access_token_minutes: int = 60
    file_encryption_key: str = ""
    storage_path: str = "./private_uploads"
    storage_backend: str = "local"
    s3_endpoint_url: str = ""
    s3_region: str = "auto"
    s3_bucket: str = ""
    s3_access_key_id: str = ""
    s3_secret_access_key: str = ""
    max_resume_bytes: int = 10 * 1024 * 1024
    cors_origins: str = "http://localhost:3000"
    auto_discovery_enabled: bool = False
    scheduler_shared_secret: str = ""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def cors_origin_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def validate_production_secrets(self) -> None:
        if self.environment in {"production", "staging"}:
            if len(self.jwt_secret_key) < 32 or self.jwt_secret_key.lower().startswith(("generate-", "change-this")):
                raise RuntimeError("Set a unique JWT_SECRET_KEY of at least 32 characters")
            if not self.file_encryption_key:
                raise RuntimeError("Set FILE_ENCRYPTION_KEY before starting outside development")
            from cryptography.fernet import Fernet
            try:
                Fernet(self.file_encryption_key.encode())
            except Exception as exc:
                raise RuntimeError("FILE_ENCRYPTION_KEY is not a valid Fernet key") from exc
        if self.storage_backend not in {"local", "s3"}:
            raise RuntimeError("STORAGE_BACKEND must be 'local' or 's3'")
        if self.storage_backend == "s3":
            required = (self.s3_endpoint_url, self.s3_bucket, self.s3_access_key_id, self.s3_secret_access_key)
            if not all(required):
                raise RuntimeError("S3 storage requires endpoint, bucket, access key, and secret key")
            if not self.s3_endpoint_url.startswith("https://"):
                raise RuntimeError("S3_ENDPOINT_URL must use HTTPS")
        if self.scheduler_shared_secret and len(self.scheduler_shared_secret) < 32:
            raise RuntimeError("SCHEDULER_SHARED_SECRET must contain at least 32 characters")


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
