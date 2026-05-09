"""
`MedVerifier` — the importable facade.

Composes the same services that power the FastAPI app (under `src.services.*`)
but with explicit dependency injection instead of module-singleton getters, so
library consumers can run multiple instances, test cleanly, and not rely on
`get_settings()` reading a .env file.

Usage:

    from medverify_core import MedVerifier

    async with MedVerifier(neo4j_uri="...", neo4j_password="...") as v:
        results = await v.verify_text("Heart attack treated with aspirin")
        for r in results:
            print(r.status, r.claim)
"""

from __future__ import annotations

from typing import List, Optional

from src.models.responses import (
    ClaimVerification,
    DiseaseInfo,
    DrugInfo,
    Entity,
    Evidence,
    VerificationStatus,
)
from src.services.gliner_client import GLiNERClient
from src.services.knowledge_graph import KnowledgeGraphService
from src.services.drug_normalizer import DrugNormalizer
from src.services.sapbert_normalizer import SapBERTNormalizer
from src.services.claim_triple_extractor import ClaimTripleExtractor
from src.services.llm_predicate_resolver import LLMPredicateResolver
from src.services.claim_verifier import ClaimVerifier

from .config import MedVerifierConfig


class MedVerifier:
    """In-process medical claim verifier.

    Construct with explicit Neo4j credentials (and optional overrides), then
    call `verify_text` / `extract_entities` / `get_drug_info` / `get_disease_info`.
    All methods are async. Use as an async context manager so the underlying
    Neo4j driver, GLiNER client, and SQLite caches are closed cleanly.

    Args:
        config: a fully-populated `MedVerifierConfig`. Mutually exclusive with kwargs.
        **kwargs: any field of `MedVerifierConfig` (`neo4j_uri=`, `neo4j_password=`, ...).
    """

    def __init__(
        self,
        config: Optional[MedVerifierConfig] = None,
        **kwargs,
    ) -> None:
        if config is not None and kwargs:
            raise ValueError("Pass either `config=` or kwargs, not both.")
        cfg = config or MedVerifierConfig(**kwargs)
        self._cfg = cfg

        # --- Build each service with explicit args (no get_*() singletons). ---

        self._gliner = GLiNERClient(
            model_name=cfg.gliner_model,
            threshold=cfg.gliner_threshold,
        )
        self._kg = KnowledgeGraphService(
            uri=cfg.neo4j_uri,
            user=cfg.neo4j_user,
            password=cfg.neo4j_password,
        )
        self._drug_norm = DrugNormalizer()
        # SapBERTNormalizer accepts an index_dir + threshold; load is lazy on first lookup.
        # The KG service auto-discovers the singleton via get_sapbert_normalizer(); we
        # construct one here primarily for explicit close() semantics. The KG falls back
        # gracefully when the index files are absent.
        self._sapbert = SapBERTNormalizer(
            index_dir=cfg.sapbert_index_dir,
            db_path=cfg.drug_norm_db,
            threshold=cfg.sapbert_threshold,
        )
        # Always construct an LLM resolver so ClaimTripleExtractor doesn't fall
        # back to the module-level singleton (which reads .env directly).
        # When enable_llm_fallback=False we pass enabled=False; the resolver
        # then short-circuits to a NONE predicate without making any API call.
        self._llm = LLMPredicateResolver(
            api_key=cfg.anthropic_api_key,
            bedrock_token=cfg.aws_bearer_token_bedrock,
            aws_region=cfg.aws_region,
            bedrock_model=cfg.bedrock_model,
            anthropic_model=cfg.llm_model,
            timeout=cfg.llm_timeout_seconds,
            min_confidence=cfg.llm_min_confidence,
            enabled=cfg.enable_llm_fallback,
        )
        self._triples = ClaimTripleExtractor(llm_resolver=self._llm)
        self._verifier = ClaimVerifier(
            entity_extractor=self._gliner,
            kg_service=self._kg,
            drug_normalizer=self._drug_norm,
            triple_extractor=self._triples,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def verify_text(self, text: str) -> List[ClaimVerification]:
        """Extract entities, infer triples, and verify each against the KG.

        Returns a list of `ClaimVerification` (one per asserted triple in `text`).
        """
        return await self._verifier.verify_text(text)

    async def extract_entities(self, text: str) -> List[Entity]:
        """Run GLiNER over `text` and return the extracted medical entities."""
        return await self._gliner.extract_entities(text)

    async def get_drug_info(self, name: str) -> Optional[DrugInfo]:
        """Aggregate drug profile (indications, contraindications, side effects, interactions)."""
        info = await self._kg.get_drug_info(name)
        return DrugInfo(**info) if info else None

    async def get_disease_info(self, name: str) -> Optional[DiseaseInfo]:
        """Aggregate disease profile (treatments, symptoms, related conditions)."""
        info = await self._kg.get_disease_info(name)
        return DiseaseInfo(**info) if info else None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def aclose(self) -> None:
        """Close Neo4j driver, GLiNER, and SQLite handles. Idempotent."""
        await self._gliner.close()
        await self._kg.close()
        await self._drug_norm.close()
        await self._sapbert.close()
        await self._llm.close()

    async def __aenter__(self) -> "MedVerifier":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.aclose()
