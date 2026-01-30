"""
MedVerify API Configuration
Loads settings from environment variables
"""

from functools import lru_cache
from typing import List
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    """Application settings loaded from environment variables"""

    # MedCAT Service
    medcat_api_url: str = "https://asmaamhadir--medcat-api-fastapi-app.modal.run"
    medcat_timeout: int = 60  # seconds (first request may be slow)

    # Neo4j
    neo4j_uri: str = ""
    neo4j_user: str = "neo4j"
    neo4j_password: str = ""

    # API Settings
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    log_level: str = "INFO"
    debug: bool = False

    # Rate Limiting
    rate_limit_per_minute: int = 60

    # API Security
    api_keys: List[str] = Field(default_factory=list)  # Empty = public access
    cors_origins: List[str] = Field(
        default_factory=lambda: ["http://localhost:8501", "http://localhost:3000"]
    )

    # Caching
    cache_ttl: int = 300  # Cache TTL in seconds (5 min)
    cache_max_size: int = 1000  # Max cached items

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8"
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
