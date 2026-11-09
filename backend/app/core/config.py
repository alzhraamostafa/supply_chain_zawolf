
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


# Resolve the backend directory independently of the terminal location.
BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    # Define typed application configuration values.
    app_name: str = "FORMA API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    # Define the SQLite database location relative to the backend directory.
    database_path: str = "../data/forma_prepared.db"

    # Load local settings from the backend .env file.
    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


# Cache one settings object for reuse across the application.
@lru_cache
def get_settings() -> Settings:
    return Settings()
