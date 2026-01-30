"""
Unit Tests for Claim Verifier Service
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.models.responses import Entity, VerificationStatus
from src.services.claim_verifier import ClaimVerifier


class TestClaimVerifier:
    """Test cases for ClaimVerifier"""

    @pytest.mark.asyncio
    async def test_verify_drug_treats_disease_supported(self, mock_gliner_client, mock_kg_service):
        """Test that drug-disease relationship is verified as SUPPORTED"""
        verifier = ClaimVerifier(mock_gliner_client, mock_kg_service)

        results = await verifier.verify_text("Metformin treats diabetes")

        assert len(results) >= 1
        assert results[0].status == VerificationStatus.SUPPORTED
        assert "Metformin" in results[0].claim.lower() or "metformin" in results[0].claim.lower()

    @pytest.mark.asyncio
    async def test_verify_no_entities_returns_unknown(self, mock_kg_service):
        """Test that text with no medical entities returns UNKNOWN"""
        mock_gliner = MagicMock()
        mock_gliner.extract_entities = AsyncMock(return_value=[])

        verifier = ClaimVerifier(mock_gliner, mock_kg_service)
        results = await verifier.verify_text("The weather is nice today")

        assert len(results) == 1
        assert results[0].status == VerificationStatus.UNKNOWN
        assert "No medical entities" in results[0].claim

    @pytest.mark.asyncio
    async def test_verify_not_found_relationship(self, mock_gliner_client):
        """Test that unknown relationships return NOT_FOUND"""
        mock_kg = MagicMock()
        mock_kg.check_drug_treats_disease = AsyncMock(return_value={"found": False, "evidence": []})
        mock_kg.check_contraindication = AsyncMock(return_value={"found": False, "evidence": []})
        mock_kg.search_entity = AsyncMock(return_value=[])

        verifier = ClaimVerifier(mock_gliner_client, mock_kg)
        results = await verifier.verify_text("Metformin treats diabetes")

        # Should return NOT_FOUND when no relationship is verified
        assert any(r.status == VerificationStatus.NOT_FOUND for r in results)

    @pytest.mark.asyncio
    async def test_normalize_name_handles_type_pattern(self):
        """Test name normalization for type patterns"""
        mock_medcat = MagicMock()
        mock_kg = MagicMock()
        verifier = ClaimVerifier(mock_medcat, mock_kg)

        # Test "diabetes type 2" -> "type 2 diabetes"
        normalized = verifier._normalize_name("diabetes type 2")
        assert "type 2" in normalized
        assert "diabetes" in normalized

    @pytest.mark.asyncio
    async def test_normalize_name_removes_suffixes(self):
        """Test that common suffixes are removed"""
        mock_medcat = MagicMock()
        mock_kg = MagicMock()
        verifier = ClaimVerifier(mock_medcat, mock_kg)

        normalized = verifier._normalize_name("Metformin hydrochloride")
        assert "hydrochloride" not in normalized
        assert "metformin" in normalized

    @pytest.mark.asyncio
    async def test_get_search_term_prefers_text(self, mock_kg_service):
        """Test that search term prefers entity.text over entity.name"""
        mock_medcat = MagicMock()
        verifier = ClaimVerifier(mock_medcat, mock_kg_service)

        entity = Entity(
            text="Hypertension",
            cui="123",
            name="Hypertensive disorder, systemic arterial",
            type="Disease",
            confidence=0.9,
            start=0,
            end=12,
            negated=False
        )

        search_term = verifier._get_search_term(entity)
        assert "hypertension" in search_term.lower()
        assert "systemic" not in search_term.lower()

    @pytest.mark.asyncio
    async def test_confidence_calculation(self, mock_kg_service):
        """Test confidence score calculation"""
        mock_gliner = MagicMock()
        verifier = ClaimVerifier(mock_gliner, mock_kg_service)

        entity1 = Entity(
            text="Drug1", cui="1", name="Drug1", type="Drug",
            confidence=0.9, start=0, end=5, negated=False
        )
        entity2 = Entity(
            text="Disease1", cui="2", name="Disease1", type="Disease",
            confidence=0.8, start=10, end=18, negated=False
        )

        kg_result = {"found": True, "evidence": [{"drug": "Drug1", "disease": "Disease1"}]}

        confidence = verifier._calculate_confidence(entity1, entity2, kg_result)

        assert 0 <= confidence <= 1
        assert confidence > 0.5  # Should be reasonably confident with evidence

    @pytest.mark.asyncio
    async def test_negated_entities_excluded(self, mock_kg_service):
        """Test that negated entities are not verified"""
        mock_gliner = MagicMock()
        mock_gliner.extract_entities = AsyncMock(return_value=[
            Entity(
                text="Metformin",
                cui="GLI_DRUG_123",
                name="Metformin",
                type="Drug",
                confidence=0.9,
                start=0,
                end=9,
                negated=True  # Negated
            ),
            Entity(
                text="diabetes",
                cui="GLI_DISEASE_456",
                name="diabetes",
                type="Disease",
                confidence=0.9,
                start=20,
                end=28,
                negated=False
            )
        ])

        verifier = ClaimVerifier(mock_gliner, mock_kg_service)
        results = await verifier.verify_text("No Metformin for diabetes")

        # Should return PARTIAL because no drug-disease pairs (drug is negated)
        assert results[0].status == VerificationStatus.PARTIAL
