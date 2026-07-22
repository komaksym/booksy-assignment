"""Application settings for the first delivery slice."""

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Load the minimal runtime configuration from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    environment: Literal["development", "test", "production"] = "development"
    tinydb_path: Path = Path("var/hardware-hub.json")
    session_secret: str
    bootstrap_admin_email: str
    bootstrap_admin_password: str
    llm_base_url: str = ""
    llm_model: str = ""
    llm_api_key: str = ""
