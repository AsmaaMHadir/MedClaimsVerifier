"""
MedVerify API
Medical Claim Verification using Knowledge Graphs

Run with: uvicorn src.main:app --reload
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

from src.config.settings import get_settings
from src.config.logging import setup_logging
from src.api.routes import router
from src.services.gliner_client import get_gliner_client
from src.services.knowledge_graph import get_knowledge_graph_service
from src.services.drug_normalizer import get_drug_normalizer
from src.services.sapbert_normalizer import get_sapbert_normalizer
from src.services.llm_predicate_resolver import get_llm_predicate_resolver
from src.services.cache import clear_all_caches, get_cache_stats

# Initialize rate limiter
limiter = Limiter(key_func=get_remote_address)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler
    - Startup: Initialize services
    - Shutdown: Cleanup connections
    """
    # Startup
    settings = get_settings()

    # Initialize structured logging
    setup_logging(log_level=settings.log_level)

    logger.info("Starting MedVerify API...")
    logger.info(f"Entity Extractor: GLiNER ({settings.gliner_model}, threshold={settings.gliner_threshold})")
    logger.info(f"Neo4j URI: {settings.neo4j_uri[:30]}..." if settings.neo4j_uri else "Neo4j URI: not configured")
    logger.info(f"Rate limit: {settings.rate_limit_per_minute}/minute")
    logger.info(f"CORS origins: {settings.cors_origins}")
    logger.info(f"API key auth: {'enabled' if settings.api_keys else 'disabled (public access)'}")

    # Initialize services (lazy loading)
    # GLiNER and Neo4j will connect on first request

    logger.info("MedVerify API started successfully")

    yield

    # Shutdown
    logger.info("Shutting down MedVerify API...")

    # Close connections
    gliner = get_gliner_client()
    await gliner.close()

    kg = get_knowledge_graph_service()
    await kg.close()

    normalizer = get_drug_normalizer()
    await normalizer.close()

    sapbert = get_sapbert_normalizer()
    await sapbert.close()

    llm_resolver = get_llm_predicate_resolver()
    await llm_resolver.close()

    # Clear caches
    clear_all_caches()

    logger.info("MedVerify API shutdown complete")


# Create FastAPI app
app = FastAPI(
    title="MedVerify API",
    description="""
## Medical Claim Verification API

Verify medical claims against a curated knowledge graph.

### Features
- **Entity Extraction**: Extract drugs, diseases, symptoms from text
- **Claim Verification**: Verify medical relationships
- **Drug Lookup**: Get indications, contraindications, side effects
- **Disease Lookup**: Get treatments and symptoms

### Data Sources
- **NLP Model**: GLiNER (zero-shot NER for medical entities)
- **Knowledge Graph**: PrimeKG (2.4M+ relationships)
    """,
    version="1.0.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc"
)

# Rate limiting
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# CORS middleware - configured from settings
settings = get_settings()
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Include routes
app.include_router(router)


# Cache stats endpoint
@app.get("/cache-stats", tags=["Admin"])
async def cache_stats():
    """Get cache statistics (for monitoring)"""
    return get_cache_stats()


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root - returns basic info"""
    return {
        "name": "MedVerify API",
        "version": "1.0.0",
        "description": "Medical Claim Verification API",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    
    settings = get_settings()
    uvicorn.run(
        "src.main:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=settings.debug
    )
