"""GeoLedger configuration management."""

import os
from pathlib import Path
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator

BASE_DIR = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore"
    )

    # Application
    APP_NAME: str = "GeoLedger"
    APP_VERSION: str = "0.1.0"
    APP_DESCRIPTION: str = "Intelligent Land Record Digitization and Validation System"
    DEBUG: bool = False

    @field_validator("DEBUG", mode="before")
    @classmethod
    def parse_debug(cls, v):
        if isinstance(v, str):
            return v.strip().lower() in ("true", "1", "yes", "debug", "dev", "development")
        return bool(v)

    # Server
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # Database
    DATABASE_URL: str = "sqlite:///./data/geoldger.db"
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20
    DB_POOL_TIMEOUT_SECONDS: int = 30
    # If unset, retain demo seeding for local SQLite while disabling it on
    # PostgreSQL so a production database is never populated with demo users.
    SEED_DEMO_DATA: Optional[bool] = None

    @field_validator("DATABASE_URL", mode="before")
    @classmethod
    def normalize_postgresql_url(cls, value):
        if isinstance(value, str) and value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @property
    def should_seed_demo_data(self) -> bool:
        if self.SEED_DEMO_DATA is not None:
            return self.SEED_DEMO_DATA
        return self.DATABASE_URL.startswith("sqlite")

    # File storage
    UPLOAD_DIR: str = "uploads"
    ORIGINAL_DIR: str = "uploads/originals"
    PROCESSED_DIR: str = "uploads/processed"
    MAX_FILE_SIZE_MB: int = 50
    ALLOWED_EXTENSIONS: set[str] = {".pdf", ".jpg", ".jpeg", ".png"}

    # Authentication
    SECRET_KEY: str = "geoldger-secret-key-change-in-production"  # Max 72 bytes for bcrypt
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 480

    # OCR
    OCR_PROVIDER: str = "tesseract"
    TESSERACT_PATH: str = r"C:\Program Files\Tesseract-OCR\tesseract.exe" if os.path.exists(r"C:\Program Files\Tesseract-OCR\tesseract.exe") else (
        r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe" if os.path.exists(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe") else ""
    )
    OCR_LANGUAGES: list[str] = ["eng", "hin", "ben"]

    # Processing
    MIN_OCR_CONFIDENCE: float = 0.3
    LOW_CONFIDENCE_THRESHOLD: float = 0.6
    HIGH_CONFIDENCE_THRESHOLD: float = 0.85

    # CORS
    CORS_ORIGINS: list[str] = ["*"]

    # Paths
    BASE_DIR: Path = BASE_DIR
    DATA_DIR: Path = BASE_DIR / "data"
    STATE_ADAPTERS_DIR: Path = BASE_DIR / "backend" / "state_adapters"


settings = Settings()
