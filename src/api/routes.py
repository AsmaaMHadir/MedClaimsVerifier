"""
MedVerify API Routes
"""

import time
from fastapi import APIRouter, HTTPException, Depends, Request
from loguru import logger
from slowapi import Limiter
from slowapi.util import get_remote_address

from src.models.requests import VerifyRequest, ExtractRequest
from src.models.responses import (
    VerifyResponse,
    ExtractResponse,
    DrugInfo,
    DiseaseInfo,
    HealthResponse,
    ErrorResponse,
    Entity,
    NeighborhoodResponse
)
from src.services.gliner_client import get_gliner_client, GLiNERClient
from src.services.knowledge_graph import get_knowledge_graph_service, KnowledgeGraphService
from src.services.claim_verifier import get_claim_verifier, ClaimVerifier
from src.services.verification_logger import get_verification_logger
from src.middleware.auth import verify_api_key
from src.config.settings import get_settings

# Rate limiter instance (shared with main app)
limiter = Limiter(key_func=get_remote_address)

router = APIRouter()


# ==================== Health Check ====================

@router.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """
    Check the health status of all services
    """
    gliner = get_gliner_client()
    kg = get_knowledge_graph_service()

    # Check GLiNER
    gliner_start = time.time()
    gliner_health = await gliner.health_check()
    gliner_latency = (time.time() - gliner_start) * 1000

    # Check Neo4j
    neo4j_start = time.time()
    neo4j_health = await kg.health_check()
    neo4j_latency = (time.time() - neo4j_start) * 1000

    # Determine overall status
    all_healthy = (
        gliner_health.get("status") == "healthy" and
        neo4j_health.get("status") == "healthy"
    )

    return HealthResponse(
        status="healthy" if all_healthy else "degraded",
        services={
            "gliner": {
                "status": gliner_health.get("status", "unknown"),
                "latency_ms": round(gliner_latency, 2),
                "model": gliner_health.get("model", "unknown")
            },
            "neo4j": {
                "status": neo4j_health.get("status", "unknown"),
                "latency_ms": round(neo4j_latency, 2)
            }
        },
        version="1.0.0"
    )


# ==================== Verification ====================

@router.post(
    "/verify",
    response_model=VerifyResponse,
    tags=["Verification"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("60/minute")
async def verify_claims(request: Request, body: VerifyRequest):
    """
    Verify medical claims in text
    
    Extracts medical entities and verifies relationships against the knowledge graph.
    
    **Example:**
    ```json
    {
      "text": "Metformin is commonly prescribed to treat Type 2 Diabetes."
    }
    ```
    """
    start_time = time.time()

    try:
        verifier = get_claim_verifier()
        claims = await verifier.verify_text(body.text)
        
        processing_time = (time.time() - start_time) * 1000

        response = VerifyResponse(
            success=True,
            claims=claims,
            warnings=[],
            processing_time_ms=round(processing_time, 2)
        )

        # Append measurement row (best-effort, never raises)
        get_verification_logger().log(body.text, response)

        return response

    except Exception as e:
        logger.error(f"Verification failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "VERIFICATION_FAILED",
                "message": str(e)
            }
        )


# ==================== Entity Extraction ====================

@router.post(
    "/extract",
    response_model=ExtractResponse,
    tags=["Extraction"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("60/minute")
async def extract_entities(request: Request, body: ExtractRequest):
    """
    Extract medical entities from text

    Uses GLiNER (zero-shot NER) to identify drugs, diseases, and symptoms.

    **Example:**
    ```json
    {
      "text": "Patient has diabetes and takes metformin daily."
    }
    ```
    """
    try:
        gliner = get_gliner_client()
        entities = await gliner.extract_entities(body.text)

        return ExtractResponse(
            success=True,
            entities=entities,
            count=len(entities)
        )

    except Exception as e:
        logger.error(f"Extraction failed: {e}")
        raise HTTPException(
            status_code=503,
            detail={
                "code": "EXTRACTION_FAILED",
                "message": str(e)
            }
        )


# ==================== Drug Information ====================

@router.get(
    "/drug/{drug_name}",
    response_model=DrugInfo,
    tags=["Knowledge Graph"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("120/minute")
async def get_drug_information(request: Request, drug_name: str):
    """
    Get comprehensive information about a drug
    
    Returns indications, contraindications, side effects, and interactions.
    
    **Example:** `/drug/metformin`
    """
    kg = get_knowledge_graph_service()
    info = await kg.get_drug_info(drug_name)
    
    if not info:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": f"Drug '{drug_name}' not found in knowledge graph"
            }
        )
    
    return DrugInfo(
        drug=info.get("drug", drug_name),
        indications=info.get("indications", []),
        contraindications=info.get("contraindications", []),
        side_effects=info.get("side_effects", []),
        interactions=info.get("interactions", [])
    )


# ==================== Disease Information ====================

@router.get(
    "/disease/{disease_name}",
    response_model=DiseaseInfo,
    tags=["Knowledge Graph"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("120/minute")
async def get_disease_information(request: Request, disease_name: str):
    """
    Get comprehensive information about a disease
    
    Returns treatments, symptoms, and related conditions.
    
    **Example:** `/disease/diabetes`
    """
    kg = get_knowledge_graph_service()
    info = await kg.get_disease_info(disease_name)
    
    if not info:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "NOT_FOUND",
                "message": f"Disease '{disease_name}' not found in knowledge graph"
            }
        )
    
    return DiseaseInfo(
        disease=info.get("disease", disease_name),
        treatments=info.get("treatments", []),
        symptoms=info.get("symptoms", []),
        related_conditions=info.get("related_conditions", [])
    )


# ==================== Neighborhood ====================

@router.get(
    "/neighborhood/{entity_type}/{entity_name}",
    response_model=NeighborhoodResponse,
    tags=["Knowledge Graph"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("120/minute")
async def get_entity_neighborhood_route(
    request: Request,
    entity_type: str,
    entity_name: str,
    limit: int = 5,
):
    """
    Return the graph neighborhood (nodes + edges) of an entity.

    - **entity_type**: "Drug" or "Disease"
    - **entity_name**: Name to match (case-insensitive contains)
    - **limit**: 1..25 neighbors, default 5

    **Example:** `/neighborhood/Drug/metformin?limit=10`
    """
    if entity_type not in {"Drug", "Disease"}:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_TYPE",
                "message": "entity_type must be 'Drug' or 'Disease'"
            }
        )
    if len(entity_name) < 2:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_NAME",
                "message": "entity_name must be at least 2 characters"
            }
        )

    capped = max(1, min(int(limit), 25))
    kg = get_knowledge_graph_service()
    return await kg.get_entity_neighborhood(entity_name, entity_type, limit=capped)


# ==================== Search ====================

@router.get(
    "/search",
    tags=["Knowledge Graph"],
    dependencies=[Depends(verify_api_key)]
)
@limiter.limit("120/minute")
async def search_entities(request: Request, q: str, type: str = None):
    """
    Search for entities in the knowledge graph
    
    **Parameters:**
    - `q`: Search query
    - `type`: Optional entity type filter (Drug, Disease, etc.)
    
    **Example:** `/search?q=diabetes&type=Disease`
    """
    if len(q) < 2:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "INVALID_QUERY",
                "message": "Search query must be at least 2 characters"
            }
        )

    kg = get_knowledge_graph_service()
    results = await kg.search_entity(q, label=type)

    return {
        "query": q,
        "type_filter": type,
        "results": results,
        "count": len(results)
    }
