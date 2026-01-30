"""
Pytest Configuration and Fixtures
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from fastapi.testclient import TestClient

from src.models.responses import Entity, ClaimVerification, VerificationStatus, Evidence


@pytest.fixture
def mock_settings():
    """Mock settings for tests"""
    with patch("src.config.settings.get_settings") as mock:
        settings = MagicMock()
        settings.neo4j_uri = "bolt://mock-neo4j:7687"
        settings.neo4j_user = "neo4j"
        settings.neo4j_password = "test"
        settings.api_keys = []  # Public access
        settings.cors_origins = ["*"]
        settings.rate_limit_per_minute = 60
        settings.cache_ttl = 300
        settings.cache_max_size = 100
        settings.log_level = "DEBUG"
        mock.return_value = settings
        yield settings


@pytest.fixture
def sample_entities():
    """Sample extracted entities for testing"""
    return [
        Entity(
            text="Metformin",
            cui="GLI_DRUG_12345",
            name="Metformin",
            type="Drug",
            confidence=0.95,
            start=0,
            end=9,
            negated=False
        ),
        Entity(
            text="Type 2 Diabetes",
            cui="GLI_DISEASE_67890",
            name="Type 2 Diabetes",
            type="Disease",
            confidence=0.92,
            start=17,
            end=32,
            negated=False
        )
    ]


@pytest.fixture
def sample_verification():
    """Sample verification result"""
    return ClaimVerification(
        claim="Metformin treats Type 2 Diabetes",
        status=VerificationStatus.SUPPORTED,
        confidence=0.89,
        entities=[
            Entity(
                text="Metformin",
                cui="GLI_DRUG_12345",
                name="Metformin",
                type="Drug",
                confidence=0.95,
                start=0,
                end=9,
                negated=False
            ),
            Entity(
                text="Type 2 Diabetes",
                cui="GLI_DISEASE_67890",
                name="Type 2 Diabetes",
                type="Disease",
                confidence=0.92,
                start=17,
                end=32,
                negated=False
            )
        ],
        evidence=[
            Evidence(
                source="PrimeKG",
                relationship="TREATS",
                subject="Metformin",
                object="type 2 diabetes mellitus"
            )
        ]
    )


@pytest.fixture
def mock_gliner_client():
    """Mock GLiNER client for testing"""
    client = MagicMock()
    client.extract_entities = AsyncMock(return_value=[
        Entity(
            text="Metformin",
            cui="GLI_DRUG_12345",
            name="Metformin",
            type="Drug",
            confidence=0.95,
            start=0,
            end=9,
            negated=False
        ),
        Entity(
            text="diabetes",
            cui="GLI_DISEASE_67890",
            name="diabetes",
            type="Disease",
            confidence=0.92,
            start=17,
            end=25,
            negated=False
        )
    ])
    client.health_check = AsyncMock(return_value={
        "status": "healthy",
        "model": "urchade/gliner_medium-v2.1",
        "entity_types": ["drug", "disease", "symptom"]
    })
    client.close = AsyncMock()
    return client


@pytest.fixture
def mock_kg_service():
    """Mock Knowledge Graph service for testing"""
    service = MagicMock()

    # Mock drug-disease check
    service.check_drug_treats_disease = AsyncMock(return_value={
        "found": True,
        "evidence": [
            {"drug": "Metformin", "disease": "type 2 diabetes mellitus", "relationship": "TREATS"}
        ]
    })

    # Mock contraindication check
    service.check_contraindication = AsyncMock(return_value={
        "found": False,
        "evidence": []
    })

    # Mock side effect check
    service.check_side_effect = AsyncMock(return_value={
        "found": False,
        "evidence": []
    })

    # Mock symptom check
    service.check_disease_symptom = AsyncMock(return_value={
        "found": False,
        "evidence": []
    })

    # Mock drug interaction check
    service.check_drug_interaction = AsyncMock(return_value={
        "found": False,
        "evidence": []
    })

    # Mock entity search
    service.search_entity = AsyncMock(return_value=[])

    # Mock drug info
    service.get_drug_info = AsyncMock(return_value={
        "drug": "Metformin",
        "indications": ["type 2 diabetes mellitus"],
        "contraindications": [],
        "side_effects": ["lactic acidosis"],
        "interactions": []
    })

    # Mock disease info
    service.get_disease_info = AsyncMock(return_value={
        "disease": "type 2 diabetes mellitus",
        "treatments": ["Metformin", "Insulin"],
        "symptoms": ["polyuria", "polydipsia"],
        "related_conditions": []
    })

    # Mock health check
    service.health_check = AsyncMock(return_value={"status": "healthy"})

    # Mock close
    service.close = AsyncMock()

    return service


@pytest.fixture
def mock_claim_verifier(mock_gliner_client, mock_kg_service):
    """Mock claim verifier with mocked dependencies"""
    from src.services.claim_verifier import ClaimVerifier
    return ClaimVerifier(mock_gliner_client, mock_kg_service)


@pytest.fixture
def test_client():
    """Create test client for API testing"""
    # Import app after fixtures are set up
    from src.main import app
    with TestClient(app) as client:
        yield client
