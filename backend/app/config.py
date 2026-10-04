from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False,
                                     hide_input_in_errors=True)
    app_env: Literal["development", "test", "production"] = "development"
    ai_provider: Literal["nvidia"] = "nvidia"
    nvidia_api_key: SecretStr = SecretStr("")
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_fast_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    nvidia_reasoning_model: str = "nvidia/nemotron-3-super-120b-a12b"
    nvidia_vision_model: str = "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"
    nvidia_embedding_model: str = "nvidia/nemotron-3-embed-1b"
    nvidia_safety_model: str = ""
    nvidia_reasoning_fallback_model: str = ""
    nvidia_fast_fallback_model: str = ""
    nvidia_request_timeout_seconds: float = Field(60, ge=1, le=300)
    nvidia_max_retries: int = Field(3, ge=0, le=5)
    nvidia_model_parameters: dict[str, dict] = Field(default_factory=lambda: {
        "nvidia/nemotron-3-super-120b-a12b": {"reasoning_effort": "low", "reasoning_budget": 4096},
        "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning": {"reasoning_budget": 512},
    })
    nvidia_embedding_dimension: int = Field(2048, ge=1, le=16000)
    nvidia_embedding_batch_size: int = Field(16, ge=1, le=32)
    ai_usage_mode: Literal["quota", "cost"] = Field("quota", validation_alias="AI_USAGE_MODE")
    enable_nvidia_safety: bool = False
    enable_vision: bool = True
    enable_reranking: bool = True
    low_memory_mode: bool = True
    database_url: str = "postgresql+asyncpg://postgres:password@localhost:5432/postgres"
    database_ssl: bool = True
    database_ssl_ca_file: Path | None = None
    database_pool_size: int = Field(3, ge=1, le=10)
    jwt_secret: SecretStr = SecretStr("development-only-change-this-secret")
    max_upload_mb: int = Field(20, ge=1, le=100)
    max_document_pages: int = Field(50, ge=1, le=200)
    max_context_tokens: int = Field(6000, ge=500, le=16000)
    max_output_tokens: int = Field(8192, ge=256, le=16000)
    demo_mode: bool = True
    admin_email: str = ""
    admin_password: SecretStr = SecretStr("")
    cookie_secure: bool = False
    allowed_origins: list[str] = ["http://localhost", "http://localhost:3000"]
    upload_dir: Path = Path("data/uploads")

    @model_validator(mode="after")
    def validate_configuration(self):
        if self.nvidia_base_url.rstrip("/") != "https://integrate.api.nvidia.com/v1":
            raise ValueError("NVIDIA_BASE_URL must use the NVIDIA-hosted HTTPS API Catalog endpoint")
        for parameters in self.nvidia_model_parameters.values():
            if set(parameters) & {"model", "messages", "stream", "max_tokens", "input", "input_type"}:
                raise ValueError("Model parameters cannot override routing, input or token limits")
        secret = self.jwt_secret.get_secret_value()
        if self.app_env == "production" and (len(secret) < 32 or "CHANGE_ME" in secret or
                                              secret.startswith("development-only")):
            raise ValueError("Set a random JWT_SECRET of at least 32 characters before production startup")
        if self.app_env == "production" and not self.cookie_secure:
            raise ValueError("Production requires COOKIE_SECURE=true and HTTPS")
        if self.app_env != "test" and not self.database_url.startswith("postgresql+asyncpg://"):
            raise ValueError("ClaimShield requires a Supabase PostgreSQL URL using postgresql+asyncpg://")
        if self.app_env == "production" and not self.database_ssl:
            raise ValueError("Production Supabase connections require DATABASE_SSL=true")
        if bool(self.admin_email) != bool(self.admin_password.get_secret_value()):
            raise ValueError("Set both ADMIN_EMAIL and ADMIN_PASSWORD, or neither")
        if self.admin_password.get_secret_value() and len(self.admin_password.get_secret_value()) < 12:
            raise ValueError("ADMIN_PASSWORD must have at least 12 characters")
        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
