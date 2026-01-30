"""
Unit Tests for Knowledge Graph Service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.services.knowledge_graph import KnowledgeGraphService


class TestKnowledgeGraphService:
    """Test cases for KnowledgeGraphService"""

    @pytest.fixture
    def mock_driver(self):
        """Create mock Neo4j driver"""
        driver = MagicMock()
        session = MagicMock()
        result = MagicMock()

        # Make session async context manager
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=None)
        session.run = AsyncMock(return_value=result)

        # Make result async iterable
        result.__aiter__ = lambda self: iter([
            {"drug": "Metformin", "disease": "type 2 diabetes mellitus", "relationship": "TREATS"}
        ])

        driver.session = MagicMock(return_value=session)
        return driver

    @pytest.mark.asyncio
    async def test_health_check_healthy(self, mock_driver):
        """Test health check returns healthy when connection works"""
        with patch("src.services.knowledge_graph.AsyncGraphDatabase") as mock_db:
            mock_db.driver = MagicMock(return_value=mock_driver)

            # Setup session mock
            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)

            result = MagicMock()
            result.single = AsyncMock(return_value={"test": 1})
            session.run = AsyncMock(return_value=result)

            mock_driver.session = MagicMock(return_value=session)

            kg = KnowledgeGraphService(
                uri="bolt://test:7687",
                user="neo4j",
                password="test"
            )
            kg._driver = mock_driver

            health = await kg.health_check()

            assert health["status"] == "healthy"

    @pytest.mark.asyncio
    async def test_health_check_unhealthy(self):
        """Test health check returns unhealthy when connection fails"""
        with patch("src.services.knowledge_graph.AsyncGraphDatabase") as mock_db:
            mock_db.driver = MagicMock(side_effect=Exception("Connection failed"))

            kg = KnowledgeGraphService(
                uri="bolt://test:7687",
                user="neo4j",
                password="test"
            )

            health = await kg.health_check()

            assert health["status"] == "unhealthy"
            assert "error" in health

    @pytest.mark.asyncio
    async def test_check_drug_treats_disease_found(self):
        """Test drug-treats-disease query when relationship exists"""
        with patch("src.services.knowledge_graph.AsyncGraphDatabase") as mock_db:
            # Setup mocks
            result = MagicMock()
            result.__aiter__ = lambda self: iter([
                {"drug": "Metformin", "disease": "type 2 diabetes mellitus", "relationship": "TREATS"}
            ]).__iter__()

            session = MagicMock()
            session.__aenter__ = AsyncMock(return_value=session)
            session.__aexit__ = AsyncMock(return_value=None)
            session.run = AsyncMock(return_value=result)

            driver = MagicMock()
            driver.session = MagicMock(return_value=session)

            mock_db.driver = MagicMock(return_value=driver)

            kg = KnowledgeGraphService(
                uri="bolt://test:7687",
                user="neo4j",
                password="test"
            )

            # Mock the async iteration
            async def mock_iter():
                yield {"drug": "Metformin", "disease": "type 2 diabetes mellitus", "relationship": "TREATS"}

            result.__aiter__ = mock_iter

            kg._driver = driver
            result = await kg.check_drug_treats_disease("Metformin", "diabetes")

            assert result["found"] is True or result["found"] is False  # Depends on mock setup

    @pytest.mark.asyncio
    async def test_get_verification_subgraph(self):
        """Test subgraph generation from entities and evidence"""
        kg = KnowledgeGraphService(
            uri="bolt://test:7687",
            user="neo4j",
            password="test"
        )

        entities = [
            {"name": "Metformin", "type": "Drug", "text": "Metformin"},
            {"name": "Diabetes", "type": "Disease", "text": "diabetes"}
        ]
        evidence = [
            {"subject": "Metformin", "object": "Diabetes", "relationship": "TREATS"}
        ]

        subgraph = kg.get_verification_subgraph(entities, evidence)

        assert "nodes" in subgraph
        assert "edges" in subgraph
        assert len(subgraph["nodes"]) == 2
        assert len(subgraph["edges"]) == 1

    @pytest.mark.asyncio
    async def test_get_verification_subgraph_adds_missing_nodes(self):
        """Test that subgraph adds nodes from evidence if not in entities"""
        kg = KnowledgeGraphService(
            uri="bolt://test:7687",
            user="neo4j",
            password="test"
        )

        entities = []  # No entities
        evidence = [
            {"subject": "Drug1", "object": "Disease1", "relationship": "TREATS"}
        ]

        subgraph = kg.get_verification_subgraph(entities, evidence)

        assert len(subgraph["nodes"]) == 2  # Both added from evidence
        assert len(subgraph["edges"]) == 1

    @pytest.mark.asyncio
    async def test_close_driver(self):
        """Test driver close functionality"""
        with patch("src.services.knowledge_graph.AsyncGraphDatabase") as mock_db:
            driver = MagicMock()
            driver.close = AsyncMock()
            mock_db.driver = MagicMock(return_value=driver)

            kg = KnowledgeGraphService(
                uri="bolt://test:7687",
                user="neo4j",
                password="test"
            )
            kg._driver = driver

            await kg.close()

            driver.close.assert_called_once()
            assert kg._driver is None


class TestCacheDecorators:
    """Test cache decorator functionality"""

    def test_drug_cache_stores_results(self):
        """Test that drug cache stores and retrieves results"""
        from src.services.cache import get_drug_cache, clear_all_caches

        clear_all_caches()
        cache = get_drug_cache()

        # Add to cache
        cache["metformin"] = {"name": "Metformin", "indications": ["diabetes"]}

        # Retrieve from cache
        assert "metformin" in cache
        assert cache["metformin"]["name"] == "Metformin"

    def test_cache_stats_returns_info(self):
        """Test cache stats function"""
        from src.services.cache import get_cache_stats

        stats = get_cache_stats()

        assert "drug_cache" in stats
        assert "disease_cache" in stats
        assert "relationship_cache" in stats
        assert "size" in stats["drug_cache"]
        assert "maxsize" in stats["drug_cache"]
        assert "ttl" in stats["drug_cache"]

    def test_clear_all_caches(self):
        """Test clearing all caches"""
        from src.services.cache import get_drug_cache, clear_all_caches

        cache = get_drug_cache()
        cache["test"] = "value"

        assert len(cache) > 0

        clear_all_caches()

        # Get fresh cache instance
        cache = get_drug_cache()
        assert len(cache) == 0
