"""
Tests for the importable `medverify_core` facade.

These are mock-driven (no live Neo4j / GLiNER / SapBERT needed) so they run in
the same suite as the FastAPI service tests. They lock in the public surface,
not the verifier semantics — those are covered in test_claim_verifier.py.
"""

from __future__ import annotations

import os
from unittest.mock import AsyncMock, patch

import pytest

from medverify_core import (
    ClaimVerification,
    Entity,
    Evidence,
    MedVerifier,
    MedVerifierConfig,
    VerificationStatus,
)


# ----------- MedVerifierConfig ----------- #


def test_config_requires_neo4j():
    with pytest.raises(ValueError, match="neo4j_uri"):
        MedVerifierConfig()


def test_config_explicit_kwargs():
    cfg = MedVerifierConfig(neo4j_uri="bolt://x:7687", neo4j_password="pw")
    assert cfg.neo4j_uri == "bolt://x:7687"
    assert cfg.neo4j_user == "neo4j"          # default
    assert cfg.enable_llm_fallback is True    # default
    assert cfg.sapbert_threshold == 0.77      # default


def test_config_from_env(monkeypatch):
    monkeypatch.setenv("NEO4J_URI", "bolt://from-env:7687")
    monkeypatch.setenv("NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("ENABLE_LLM_FALLBACK", "false")
    monkeypatch.setenv("SAPBERT_THRESHOLD", "0.85")

    cfg = MedVerifierConfig.from_env()

    assert cfg.neo4j_uri == "bolt://from-env:7687"
    assert cfg.neo4j_password == "secret"
    assert cfg.enable_llm_fallback is False    # bool coercion
    assert cfg.sapbert_threshold == 0.85       # float coercion


# ----------- MedVerifier construction ----------- #


def test_construct_with_explicit_creds():
    """No env reads: full config injected directly."""
    v = MedVerifier(
        neo4j_uri="bolt://x:7687",
        neo4j_password="pw",
        enable_llm_fallback=False,
    )
    assert isinstance(v, MedVerifier)
    # LLM resolver should be present-but-disabled, not None.
    assert v._llm is not None
    assert v._llm._enabled is False
    assert v._llm._mode == "disabled"


def test_construct_rejects_both_config_and_kwargs():
    cfg = MedVerifierConfig(neo4j_uri="bolt://x", neo4j_password="pw")
    with pytest.raises(ValueError, match="config"):
        MedVerifier(config=cfg, neo4j_uri="bolt://other")


def test_llm_fallback_off_skips_anthropic_import():
    """With enable_llm_fallback=False, the anthropic client is never instantiated."""
    v = MedVerifier(
        neo4j_uri="bolt://x:7687",
        neo4j_password="pw",
        enable_llm_fallback=False,
    )
    # _client is the lazy anthropic client; should be None until first call.
    assert v._llm._client is None
    # And because the resolver is disabled, no calls would ever fire.
    assert v._llm._enabled is False


# ----------- verify_text wires to ClaimVerifier ----------- #


@pytest.mark.asyncio
async def test_verify_text_delegates_to_claim_verifier():
    """The facade should pass `text` straight to ClaimVerifier.verify_text and return its output."""
    fake_result = [
        ClaimVerification(
            claim="aspirin treats Heart attack",
            status=VerificationStatus.SUPPORTED,
            confidence=0.81,
            entities=[
                Entity(text="aspirin", cui="x", name="aspirin",
                       type="Drug", confidence=0.9),
                Entity(text="Heart attack", cui="y", name="Heart attack",
                       type="Disease", confidence=0.9),
            ],
            evidence=[
                Evidence(source="OptimusKG", relationship="TREATS",
                         subject="ASPIRIN", object="myocardial infarction"),
            ],
            asserted_predicate="TREATS",
            evidence_predicate="TREATS",
            negated=False,
        )
    ]

    v = MedVerifier(
        neo4j_uri="bolt://x:7687",
        neo4j_password="pw",
        enable_llm_fallback=False,
    )
    with patch.object(v._verifier, "verify_text", new=AsyncMock(return_value=fake_result)) as mock:
        out = await v.verify_text("Heart attack treated with aspirin")

    mock.assert_awaited_once_with("Heart attack treated with aspirin")
    assert len(out) == 1
    assert out[0].status == VerificationStatus.SUPPORTED
    assert out[0].evidence[0].subject == "ASPIRIN"


# ----------- async-context-manager closes underlying services ----------- #


@pytest.mark.asyncio
async def test_async_context_manager_closes_all_services():
    v = MedVerifier(
        neo4j_uri="bolt://x:7687",
        neo4j_password="pw",
        enable_llm_fallback=False,
    )
    # Patch every underlying close()
    with patch.object(v._gliner, "close", new=AsyncMock()) as gliner_close, \
         patch.object(v._kg, "close", new=AsyncMock()) as kg_close, \
         patch.object(v._drug_norm, "close", new=AsyncMock()) as drug_close, \
         patch.object(v._sapbert, "close", new=AsyncMock()) as sapbert_close, \
         patch.object(v._llm, "close", new=AsyncMock()) as llm_close:

        async with v:
            pass  # exit triggers aclose()

        gliner_close.assert_awaited_once()
        kg_close.assert_awaited_once()
        drug_close.assert_awaited_once()
        sapbert_close.assert_awaited_once()
        llm_close.assert_awaited_once()
