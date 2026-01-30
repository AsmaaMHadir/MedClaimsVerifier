"""
API Endpoint Tests

Note: These tests use mocking to avoid requiring actual GLiNER and Neo4j connections.
"""

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient


# Create test fixtures that mock the lifespan dependencies
@pytest.fixture
def mock_services():
    """Mock all external services"""
    with patch("src.services.gliner_client.get_gliner_client") as mock_gliner, \
         patch("src.services.knowledge_graph.get_knowledge_graph_service") as mock_kg, \
         patch("src.config.logging.setup_logging"):

        # Setup GLiNER mock
        gliner_client = MagicMock()
        gliner_client.health_check = AsyncMock(return_value={
            "status": "healthy",
            "model": "urchade/gliner_medium-v2.1",
            "entity_types": ["drug", "disease", "symptom"]
        })
        gliner_client.extract_entities = AsyncMock(return_value=[])
        gliner_client.close = AsyncMock()
        mock_gliner.return_value = gliner_client

        # Setup KG mock
        kg_service = MagicMock()
        kg_service.health_check = AsyncMock(return_value={"status": "healthy"})
        kg_service.get_drug_info = AsyncMock(return_value=None)
        kg_service.get_disease_info = AsyncMock(return_value=None)
        kg_service.search_entity = AsyncMock(return_value=[])
        kg_service.close = AsyncMock()
        mock_kg.return_value = kg_service

        yield {
            "gliner": gliner_client,
            "kg": kg_service
        }


@pytest.fixture
def client(mock_services):
    """Create test client with mocked services"""
    from src.main import app
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


class TestRootEndpoint:
    """Tests for / root endpoint"""

    def test_root_returns_api_info(self, client):
        """Test root endpoint returns API info"""
        response = client.get("/")

        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "MedVerify API"
        assert data["version"] == "1.0.0"
        assert "docs" in data
        assert "health" in data


class TestCacheStatsEndpoint:
    """Tests for /cache-stats endpoint"""

    def test_cache_stats_returns_info(self, client):
        """Test cache stats endpoint returns cache info"""
        response = client.get("/cache-stats")

        assert response.status_code == 200
        data = response.json()
        assert "drug_cache" in data
        assert "disease_cache" in data
        assert "relationship_cache" in data


class TestHealthEndpoint:
    """Tests for /health endpoint"""

    def test_health_endpoint_returns_200(self, client, mock_services):
        """Test health endpoint returns 200"""
        response = client.get("/health")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "services" in data
        assert "version" in data


class TestVerifyEndpoint:
    """Tests for /verify endpoint"""

    def test_verify_requires_text(self, client):
        """Test verify endpoint requires text field"""
        response = client.post("/verify", json={})

        assert response.status_code == 422  # Validation error

    def test_verify_with_valid_text(self, client, mock_services):
        """Test verify endpoint with valid medical text"""
        with patch("src.services.claim_verifier.get_claim_verifier") as mock_verifier:
            from src.models.responses import ClaimVerification, VerificationStatus

            verifier = MagicMock()
            verifier.verify_text = AsyncMock(return_value=[
                ClaimVerification(
                    claim="Test claim",
                    status=VerificationStatus.SUPPORTED,
                    confidence=0.9,
                    entities=[],
                    evidence=[]
                )
            ])
            mock_verifier.return_value = verifier

            response = client.post(
                "/verify",
                json={"text": "Metformin treats diabetes"}
            )

            assert response.status_code == 200
            data = response.json()
            assert data["success"] is True
            assert "claims" in data
            assert "processing_time_ms" in data


class TestExtractEndpoint:
    """Tests for /extract endpoint"""

    def test_extract_requires_text(self, client):
        """Test extract endpoint requires text field"""
        response = client.post("/extract", json={})

        assert response.status_code == 422  # Validation error

    def test_extract_with_valid_text(self, client, mock_services):
        """Test extract endpoint with valid medical text"""
        from src.models.responses import Entity

        mock_services["gliner"].extract_entities = AsyncMock(return_value=[
            Entity(
                text="Metformin",
                cui="GLI_DRUG_12345",
                name="Metformin",
                type="Drug",
                confidence=0.9,
                start=0,
                end=9,
                negated=False
            )
        ])

        response = client.post(
            "/extract",
            json={"text": "Patient takes Metformin"}
        )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert "entities" in data
        assert "count" in data


class TestSearchEndpoint:
    """Tests for /search endpoint"""

    def test_search_requires_query(self, client):
        """Test search endpoint requires q parameter"""
        response = client.get("/search")

        assert response.status_code == 422  # Missing required param

    def test_search_with_short_query_fails(self, client):
        """Test search with query less than 2 chars fails"""
        response = client.get("/search?q=a")

        assert response.status_code == 400
        assert "at least 2 characters" in response.json()["detail"]["message"]

    def test_search_with_valid_query(self, client, mock_services):
        """Test search with valid query"""
        mock_services["kg"].search_entity = AsyncMock(return_value=[
            {"name": "Metformin", "id": "123", "labels": ["Drug"]}
        ])

        response = client.get("/search?q=metformin")

        assert response.status_code == 200
        data = response.json()
        assert "results" in data
        assert "count" in data


class TestDrugEndpoint:
    """Tests for /drug/{drug_name} endpoint"""

    def test_drug_not_found(self, mock_services):
        """Test drug endpoint returns 404 when not found"""
        mock_services["kg"].get_drug_info = AsyncMock(return_value=None)

        from src.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/drug/unknowndrug")
            assert response.status_code == 404

    @pytest.mark.skip(reason="Requires integration test setup with actual Neo4j")
    def test_drug_found(self, mock_services):
        """Test drug endpoint returns drug info - requires integration test"""
        pass


class TestDiseaseEndpoint:
    """Tests for /disease/{disease_name} endpoint"""

    def test_disease_not_found(self, mock_services):
        """Test disease endpoint returns 404 when not found"""
        mock_services["kg"].get_disease_info = AsyncMock(return_value=None)

        from src.main import app
        with TestClient(app, raise_server_exceptions=False) as client:
            response = client.get("/disease/unknowndisease")
            assert response.status_code == 404

    @pytest.mark.skip(reason="Requires integration test setup with actual Neo4j")
    def test_disease_found(self, mock_services):
        """Test disease endpoint returns disease info - requires integration test"""
        pass
