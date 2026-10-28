"""Application configuration management using Pydantic v2 Settings."""

from functools import lru_cache
from typing import List, Union
import json
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Core settings and environment variables for the Text-to-SQL backend."""

    # Project Information
    PROJECT_NAME: str = "Self-Healing Text-to-SQL Analytics Agent"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api/v1"

    # Groq Cloud API Configuration
    GROQ_API_KEY: str = Field(
        default="",
        description="Groq API key for low-latency LLM inference",
    )
    GROQ_MODEL: str = Field(
        default="llama-3.3-70b-versatile",
        description="Default Groq LLM model used for SQL synthesis and reflection",
    )

    # Security & Fernet Encryption
    ENCRYPTION_KEY: str = Field(
        default="",
        description="Fernet symmetric encryption key for credential at-rest protection",
    )

    # Database Execution Guardrails
    DATABASE_TIMEOUT_SECONDS: int = Field(
        default=10,
        description="Hard query statement timeout in seconds",
        ge=1,
        le=60,
    )
    DEFAULT_ROW_LIMIT: int = Field(
        default=500,
        description="Maximum row limit capped or injected on root SELECT queries",
        ge=1,
        le=5000,
    )
    MAX_RETRIES: int = Field(
        default=3,
        description="Maximum bounded attempts for self-healing error recovery",
        ge=1,
        le=5,
    )
    SCHEMA_CACHE_TTL_SECONDS: int = Field(
        default=900,
        description="Schema introspection metadata TTL in seconds (15 minutes default)",
        ge=60,
    )
    AUTO_SEED_DEMO: bool = Field(
        default=True,
        description="Automatically seed and register demo database on startup",
    )
    DEMO_DB_FILENAME: str = Field(
        default="demo_ecommerce.db",
        description="Filename for the SQLite demo database",
    )

    # SQLAlchemy Dynamic Connection Pool Settings
    SQL_POOL_SIZE: int = Field(default=5, ge=1, le=50)
    SQL_MAX_OVERFLOW: int = Field(default=10, ge=0, le=50)
    SQL_POOL_TIMEOUT: int = Field(default=30, ge=5, le=120)

    # CORS Configuration
    CORS_ORIGINS: Union[List[str], str] = Field(
        default=["http://localhost:3000", "http://127.0.0.1:3000"],
        description="Allowed CORS origin domains",
    )

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def assemble_cors_origins(cls, v: Union[str, List[str]]) -> List[str]:
        if isinstance(v, str):
            if v.startswith("[") and v.endswith("]"):
                try:
                    parsed = json.loads(v)
                    if isinstance(parsed, list):
                        return [str(item) for item in parsed]
                except json.JSONDecodeError:
                    pass
            return [i.strip() for i in v.split(",") if i.strip()]
        return v

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env", "../.env"),
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Retrieve cached application settings instance."""
    return Settings()
