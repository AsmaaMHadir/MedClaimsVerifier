"""
API Key Authentication Middleware
Simple API key verification via X-API-Key header
"""

from fastapi import HTTPException, Security, Depends
from fastapi.security import APIKeyHeader
from loguru import logger

from src.config.settings import get_settings

# API key header configuration
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def get_api_key(api_key: str = Security(api_key_header)) -> str | None:
    """Extract API key from header (returns None if not present)."""
    return api_key


async def verify_api_key(api_key: str = Security(api_key_header)) -> bool:
    """
    Verify the API key from the X-API-Key header.

    If no API keys are configured (empty list), public access is allowed.
    If API keys are configured, the provided key must match one of them.

    Returns:
        True if authenticated or public access is allowed

    Raises:
        HTTPException: 401 if key is missing or invalid when required
    """
    settings = get_settings()

    # If no API keys configured, allow public access
    if not settings.api_keys:
        return True

    # API keys are configured, so authentication is required
    if not api_key:
        logger.warning("API request without API key (keys required)")
        raise HTTPException(
            status_code=401,
            detail="API key required. Provide X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    if api_key not in settings.api_keys:
        logger.warning(f"Invalid API key attempted: {api_key[:8]}...")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "ApiKey"},
        )

    logger.debug(f"API key verified: {api_key[:8]}...")
    return True
