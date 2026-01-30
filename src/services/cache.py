"""
Response Caching Service
TTL-based caching for Neo4j lookups to improve performance
"""

from functools import wraps
from typing import Any, Callable, TypeVar
from cachetools import TTLCache
from loguru import logger

from src.config.settings import get_settings

# Type variable for generic cache decorator
T = TypeVar("T")

# Global cache instances
_drug_cache: TTLCache | None = None
_disease_cache: TTLCache | None = None
_relationship_cache: TTLCache | None = None


def get_drug_cache() -> TTLCache:
    """Get or create drug info cache."""
    global _drug_cache
    if _drug_cache is None:
        settings = get_settings()
        _drug_cache = TTLCache(maxsize=settings.cache_max_size, ttl=settings.cache_ttl)
        logger.info(f"Drug cache initialized (max={settings.cache_max_size}, ttl={settings.cache_ttl}s)")
    return _drug_cache


def get_disease_cache() -> TTLCache:
    """Get or create disease info cache."""
    global _disease_cache
    if _disease_cache is None:
        settings = get_settings()
        _disease_cache = TTLCache(maxsize=settings.cache_max_size, ttl=settings.cache_ttl)
        logger.info(f"Disease cache initialized (max={settings.cache_max_size}, ttl={settings.cache_ttl}s)")
    return _disease_cache


def get_relationship_cache() -> TTLCache:
    """Get or create relationship query cache."""
    global _relationship_cache
    if _relationship_cache is None:
        settings = get_settings()
        # Larger cache for relationships (more variety)
        _relationship_cache = TTLCache(maxsize=settings.cache_max_size * 5, ttl=settings.cache_ttl)
        logger.info(f"Relationship cache initialized (max={settings.cache_max_size * 5}, ttl={settings.cache_ttl}s)")
    return _relationship_cache


def cached_drug_lookup(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to cache drug lookup results."""
    @wraps(func)
    def wrapper(self, drug_name: str, *args, **kwargs) -> T:
        cache = get_drug_cache()
        cache_key = drug_name.lower().strip()

        if cache_key in cache:
            logger.debug(f"Cache hit: drug '{cache_key}'")
            return cache[cache_key]

        result = func(self, drug_name, *args, **kwargs)
        cache[cache_key] = result
        logger.debug(f"Cache miss: drug '{cache_key}' cached")
        return result

    return wrapper


def cached_disease_lookup(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to cache disease lookup results."""
    @wraps(func)
    def wrapper(self, disease_name: str, *args, **kwargs) -> T:
        cache = get_disease_cache()
        cache_key = disease_name.lower().strip()

        if cache_key in cache:
            logger.debug(f"Cache hit: disease '{cache_key}'")
            return cache[cache_key]

        result = func(self, disease_name, *args, **kwargs)
        cache[cache_key] = result
        logger.debug(f"Cache miss: disease '{cache_key}' cached")
        return result

    return wrapper


def cached_relationship(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to cache relationship query results."""
    @wraps(func)
    def wrapper(self, *args, **kwargs) -> T:
        cache = get_relationship_cache()
        # Create cache key from function name and all arguments
        cache_key = f"{func.__name__}:{':'.join(str(a).lower().strip() for a in args)}"

        if cache_key in cache:
            logger.debug(f"Cache hit: relationship '{cache_key}'")
            return cache[cache_key]

        result = func(self, *args, **kwargs)
        cache[cache_key] = result
        logger.debug(f"Cache miss: relationship '{cache_key}' cached")
        return result

    return wrapper


def clear_all_caches() -> None:
    """Clear all caches (useful for testing or forced refresh)."""
    global _drug_cache, _disease_cache, _relationship_cache

    if _drug_cache:
        _drug_cache.clear()
    if _disease_cache:
        _disease_cache.clear()
    if _relationship_cache:
        _relationship_cache.clear()

    logger.info("All caches cleared")


def get_cache_stats() -> dict:
    """Get statistics about cache usage."""
    drug = get_drug_cache()
    disease = get_disease_cache()
    relationship = get_relationship_cache()

    return {
        "drug_cache": {
            "size": len(drug),
            "maxsize": drug.maxsize,
            "ttl": drug.ttl,
        },
        "disease_cache": {
            "size": len(disease),
            "maxsize": disease.maxsize,
            "ttl": disease.ttl,
        },
        "relationship_cache": {
            "size": len(relationship),
            "maxsize": relationship.maxsize,
            "ttl": relationship.ttl,
        },
    }
