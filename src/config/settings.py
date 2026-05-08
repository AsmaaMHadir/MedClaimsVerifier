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

    # Entity Extraction (GLiNER)
    gliner_model: str = "urchade/gliner_medium-v2.1"
    gliner_threshold: float = 0.5

    # LLM Predicate Fallback (only fires when rule-based predicate matcher returns NONE)
    # Two providers supported:
    #   - Direct Anthropic API: set ANTHROPIC_API_KEY
    #   - AWS Bedrock:          set AWS_BEARER_TOKEN_BEDROCK + AWS_REGION + BEDROCK_MODEL
    # Bedrock takes precedence if both are set.
    anthropic_api_key: str = ""
    aws_bearer_token_bedrock: str = ""
    aws_region: str = "us-east-1"
    bedrock_model: str = ""                  # e.g. "us.anthropic.claude-sonnet-4-20250514-v1:0"
    llm_fallback_enabled: bool = True
    llm_model: str = "claude-haiku-4-5"      # fallback for direct Anthropic API path
    llm_timeout_seconds: float = 8.0
    llm_min_confidence: float = 0.6          # below this, treat as NONE

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
        default_factory=lambda: [
            "http://localhost:8501",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            "http://127.0.0.1:8501",
        ]
    )

    # Caching
    cache_ttl: int = 300  # Cache TTL in seconds (5 min)
    cache_max_size: int = 1000  # Max cached items

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache()
def get_settings() -> Settings:
    """Get cached settings instance"""
    return Settings()
