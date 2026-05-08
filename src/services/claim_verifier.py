"""
Claim Verifier Service

Triple-driven verification:
  1. GLiNER extracts entities.
  2. ClaimTripleExtractor produces (subject, predicate, object, asserted)
     triples by reading the verb/intent phrase between each entity pair.
  3. For each triple we verify the SPECIFIC asserted relation against the
     knowledge graph, with two enrichments:
       - Drug names get a lazy RxNorm cascade (brand → generic ingredients).
       - We also probe the "opposite" relation so we can mark a verdict as
         CONTRADICTED when the KG provides the inverse of what the user said.
"""

from typing import Awaitable, Callable, List, Optional
from loguru import logger

from src.models.responses import (
    Entity,
    Evidence,
    ClaimVerification,
    VerificationStatus,
)
from src.services.gliner_client import GLiNERClient, get_gliner_client
from src.services.knowledge_graph import (
    KnowledgeGraphService,
    get_knowledge_graph_service,
)
from src.services.drug_normalizer import DrugNormalizer, get_drug_normalizer
from src.services.claim_triple_extractor import (
    ClaimTriple,
    ClaimTripleExtractor,
    get_claim_triple_extractor,
)


# Pretty verb fragments per predicate, used when rendering the user-facing claim
_VERB_TEMPLATES: dict[str, str] = {
    "TREATS": "treats",
    "CAUSES_SIDE_EFFECT": "may cause",
    "CONTRAINDICATED_FOR": "is contraindicated for",
    "INTERACTS_WITH": "interacts with",
    "HAS_SYMPTOM": "presents with",
}

# Pre-conjugated negated forms (avoids brittle string surgery on "treats" -> "treat")
_NEGATED_VERB_TEMPLATES: dict[str, str] = {
    "TREATS": "does not treat",
    "CAUSES_SIDE_EFFECT": "does not cause",
    "CONTRAINDICATED_FOR": "is not contraindicated for",
    "INTERACTS_WITH": "does not interact with",
    "HAS_SYMPTOM": "does not present with",
}


class ClaimVerifier:
    """Triple-driven medical claim verifier."""

    def __init__(
        self,
        entity_extractor: GLiNERClient = None,
        kg_service: KnowledgeGraphService = None,
        drug_normalizer: DrugNormalizer = None,
        triple_extractor: ClaimTripleExtractor = None,
    ):
        self.extractor = entity_extractor or get_gliner_client()
        self.kg = kg_service or get_knowledge_graph_service()
        self.drug_normalizer = drug_normalizer or get_drug_normalizer()
        self.triple_extractor = triple_extractor or get_claim_triple_extractor()

    # =====================================================================
    # Public entry point
    # =====================================================================

    async def verify_text(self, text: str) -> List[ClaimVerification]:
        logger.info(f"Verifying text: {text[:100]}...")

        entities = await self.extractor.extract_entities(text)

        if not entities:
            return [ClaimVerification(
                claim="No medical entities detected",
                status=VerificationStatus.UNKNOWN,
                confidence=0.0,
                entities=[],
                evidence=[],
            )]

        triples = await self.triple_extractor.extract(text, entities)

        if not triples:
            # Entities were recognised but no relationship was asserted — emit a
            # single PARTIAL summary rather than fabricating verdicts.
            return [ClaimVerification(
                claim="Medical entities detected but no specific relationship asserted",
                status=VerificationStatus.PARTIAL,
                confidence=0.5,
                entities=entities,
                evidence=[],
            )]

        verifications: List[ClaimVerification] = []
        for triple in triples:
            v = await self._verify_triple(text, triple)
            if v is not None:
                verifications.append(v)

        return verifications or [ClaimVerification(
            claim="Medical entities detected but no specific relationship verified",
            status=VerificationStatus.PARTIAL,
            confidence=0.5,
            entities=entities,
            evidence=[],
        )]

    # =====================================================================
    # Triple verification — dispatch + opposite-relation contradiction logic
    # =====================================================================

    async def _verify_triple(self, text: str, t: ClaimTriple) -> Optional[ClaimVerification]:
        """
        Verify a single ClaimTriple against the knowledge graph. Always probes
        the asserted relation first; on miss, probes the relevant "opposite"
        relation so we can label CONTRADICTED.
        """
        pred = t.predicate
        if pred == "TREATS":
            return await self._verify_treats(t)
        if pred == "CONTRAINDICATED_FOR":
            return await self._verify_contraindicated(t)
        if pred == "CAUSES_SIDE_EFFECT":
            return await self._verify_side_effect(t)
        if pred == "INTERACTS_WITH":
            return await self._verify_interaction(t)
        if pred == "HAS_SYMPTOM":
            return await self._verify_symptom(t)
        return None  # unknown predicate, skip

    # ---- TREATS ----

    async def _verify_treats(self, t: ClaimTriple) -> ClaimVerification:
        """User asserted: <drug> TREATS <disease/symptom>."""
        disease_name = self._get_search_term(t.object)

        # Direct probe
        result, used_drug = await self._query_with_drug_fallback(
            t.subject, lambda d: self.kg.check_drug_treats_disease(d, disease_name)
        )
        if result["found"]:
            return self._make_verdict(
                triple=t,
                status=self._status_from_assertion(found=True, asserted=t.asserted, predicate_inverted=False),
                kg_result=result,
                kg_predicate="TREATS",
                used_drug=used_drug,
                relationship_label="TREATS",
                subj_key="drug", obj_key="disease",
            )

        # Opposite probes for contradiction signalling
        contra, used_drug2 = await self._query_with_drug_fallback(
            t.subject, lambda d: self.kg.check_contraindication(d, disease_name)
        )
        if contra["found"]:
            status = self._status_for_opposite(t.asserted)
            explanation = (
                f"You asserted that {t.subject.text} treats {t.object.text}, but the "
                f"clinical evidence indicates this combination is contraindicated."
                if t.asserted else
                f"No treatment relationship found, which is consistent with the denial. "
                f"For context: {t.subject.text} is recorded as contraindicated for "
                f"{t.object.text}."
            )
            return self._make_verdict(
                triple=t,
                status=status,
                kg_result=contra,
                kg_predicate="CONTRAINDICATED_FOR",
                used_drug=used_drug2,
                relationship_label="CONTRAINDICATED_FOR",
                subj_key="drug", obj_key="condition",
                explanation=explanation,
            )

        # If the object was tagged as a Symptom, the KG may only have it as an
        # Effect node — in that case the inverse "drug causes effect" lookup
        # detects a contradiction.
        if t.object.type in {"Symptom", "Effect"}:
            side, used_drug3 = await self._query_with_drug_fallback(
                t.subject, lambda d: self.kg.check_side_effect(d, disease_name)
            )
            if side["found"]:
                status = self._status_for_opposite(t.asserted)
                explanation = (
                    f"You asserted that {t.subject.text} treats {t.object.text}, but "
                    f"clinical evidence records {t.object.text} as a side effect of "
                    f"{used_drug3 or t.subject.text}, not as something it treats."
                    if t.asserted else
                    f"No treatment relationship found, which is consistent with the denial. "
                    f"For context: {t.object.text} is recorded as a side effect of "
                    f"{used_drug3 or t.subject.text}."
                )
                return self._make_verdict(
                    triple=t,
                    status=status,
                    kg_result=side,
                    kg_predicate="CAUSES_SIDE_EFFECT",
                    used_drug=used_drug3,
                    relationship_label="CAUSES_SIDE_EFFECT",
                    subj_key="drug", obj_key="effect",
                    explanation=explanation,
                )

        return self._not_found(t)

    # ---- CONTRAINDICATED_FOR ----

    async def _verify_contraindicated(self, t: ClaimTriple) -> ClaimVerification:
        """User asserted: <drug> is contraindicated in <condition>."""
        cond_name = self._get_search_term(t.object)
        result, used_drug = await self._query_with_drug_fallback(
            t.subject, lambda d: self.kg.check_contraindication(d, cond_name)
        )
        if result["found"]:
            return self._make_verdict(
                triple=t,
                status=self._status_from_assertion(True, t.asserted, False),
                kg_result=result, kg_predicate="CONTRAINDICATED_FOR",
                used_drug=used_drug,
                relationship_label="CONTRAINDICATED_FOR",
                subj_key="drug", obj_key="condition",
            )

        # Opposite: KG has TREATS → user wrong
        treats, used_drug2 = await self._query_with_drug_fallback(
            t.subject, lambda d: self.kg.check_drug_treats_disease(d, cond_name)
        )
        if treats["found"]:
            status = self._status_for_opposite(t.asserted)
            explanation = (
                f"You asserted that {t.subject.text} is contraindicated in "
                f"{t.object.text}, but clinical evidence shows it is in fact used to treat it."
                if t.asserted else
                f"No contraindication on record, which is consistent with the denial. "
                f"For context: {t.subject.text} is used to treat {t.object.text}."
            )
            return self._make_verdict(
                triple=t, status=status,
                kg_result=treats, kg_predicate="TREATS",
                used_drug=used_drug2,
                relationship_label="TREATS",
                subj_key="drug", obj_key="disease",
                explanation=explanation,
            )
        return self._not_found(t)

    # ---- CAUSES_SIDE_EFFECT ----

    async def _verify_side_effect(self, t: ClaimTriple) -> ClaimVerification:
        """User asserted: <drug> causes <symptom/effect>."""
        eff_name = self._get_search_term(t.object)
        result, used_drug = await self._query_with_drug_fallback(
            t.subject, lambda d: self.kg.check_side_effect(d, eff_name)
        )
        if result["found"]:
            return self._make_verdict(
                triple=t, status=self._status_from_assertion(True, t.asserted, False),
                kg_result=result, kg_predicate="CAUSES_SIDE_EFFECT",
                used_drug=used_drug,
                relationship_label="CAUSES_SIDE_EFFECT",
                subj_key="drug", obj_key="effect",
            )

        # Opposite: KG has TREATS → user wrong (drug treats it, doesn't cause it)
        treats, used_drug2 = await self._query_with_drug_fallback(
            t.subject, lambda d: self.kg.check_drug_treats_disease(d, eff_name)
        )
        if treats["found"]:
            status = self._status_for_opposite(t.asserted)
            explanation = (
                f"You asserted that {t.subject.text} causes {t.object.text}, but "
                f"clinical evidence shows it is used to treat {t.object.text}."
                if t.asserted else
                f"No causal relationship on record, which is consistent with the denial. "
                f"For context: {t.subject.text} is used to treat {t.object.text}."
            )
            return self._make_verdict(
                triple=t, status=status,
                kg_result=treats, kg_predicate="TREATS",
                used_drug=used_drug2,
                relationship_label="TREATS",
                subj_key="drug", obj_key="disease",
                explanation=explanation,
            )
        return self._not_found(t)

    # ---- INTERACTS_WITH ----

    async def _verify_interaction(self, t: ClaimTriple) -> ClaimVerification:
        """User asserted: <drug A> interacts with <drug B>. Cascade on both."""
        async def query(d1: str, d2: str):
            return await self.kg.check_drug_interaction(d1, d2)

        primary1 = self._get_search_term(t.subject)
        primary2 = self._get_search_term(t.object)
        result = await query(primary1, primary2)
        used1, used2 = primary1, primary2

        if not result["found"]:
            await self._normalize_drug(t.subject)
            await self._normalize_drug(t.object)
            cands1 = [primary1] + [c for c in self._extra_drug_candidates(t.subject, primary1)]
            cands2 = [primary2] + [c for c in self._extra_drug_candidates(t.object, primary2)]
            for c1 in cands1:
                for c2 in cands2:
                    if c1 == primary1 and c2 == primary2:
                        continue
                    r = await query(c1, c2)
                    if r["found"]:
                        result, used1, used2 = r, c1, c2
                        break
                if result["found"]:
                    break

        if result["found"]:
            return self._make_verdict(
                triple=t,
                status=self._status_from_assertion(True, t.asserted, False),
                kg_result=result, kg_predicate="INTERACTS_WITH",
                used_drug=used1,
                relationship_label="INTERACTS_WITH",
                subj_key="drug1", obj_key="drug2",
                used_object=used2,
            )
        return self._not_found(t)

    # ---- HAS_SYMPTOM ----

    async def _verify_symptom(self, t: ClaimTriple) -> ClaimVerification:
        """User asserted: <disease> presents with <symptom>."""
        dis = self._get_search_term(t.subject)
        sym = self._get_search_term(t.object)
        result = await self.kg.check_disease_symptom(dis, sym)
        if result["found"]:
            return self._make_verdict(
                triple=t,
                status=self._status_from_assertion(True, t.asserted, False),
                kg_result=result, kg_predicate="HAS_SYMPTOM",
                used_drug=None,
                relationship_label="HAS_SYMPTOM",
                subj_key="disease", obj_key="symptom",
            )
        return self._not_found(t)

    # =====================================================================
    # Helpers — drug normalization, search-term selection, verdict assembly
    # =====================================================================

    async def _normalize_drug(self, drug: Entity) -> None:
        if drug.normalization_source is not None or drug.normalized_name is not None:
            return
        if not (drug.text or drug.name):
            return
        nd = await self.drug_normalizer.normalize(drug.text or drug.name)
        if nd.canonical:
            drug.normalized_name = nd.canonical
            drug.normalized_ingredients = nd.ingredients
            drug.normalization_source = nd.source
            drug.normalization_score = nd.score
            drug.normalization_id = nd.rxcui

    def _extra_drug_candidates(self, drug: Entity, primary: str) -> list[str]:
        cands: list[str] = []
        for c in (drug.normalized_ingredients or
                  ([drug.normalized_name] if drug.normalized_name else [])):
            if c and c != primary and c not in cands:
                cands.append(c)
        return cands

    async def _query_with_drug_fallback(
        self,
        drug: Entity,
        query_fn: Callable[[str], Awaitable[dict]],
    ):
        """Try original; on miss, lazily resolve via RxNorm and retry per ingredient."""
        primary = self._get_search_term(drug)
        result = await query_fn(primary)
        if result["found"]:
            return result, primary

        await self._normalize_drug(drug)
        for cand in self._extra_drug_candidates(drug, primary):
            r = await query_fn(cand)
            if r["found"]:
                return r, cand
        return result, primary

    def _get_search_term(self, entity: Entity) -> str:
        search_term = entity.text if entity.text else entity.name
        return self._normalize_name(search_term)

    @staticmethod
    def _normalize_name(name: str) -> str:
        import re
        n = (name or "").lower().strip()
        for suffix in [" hydrochloride", " sodium", " (disease)", " mellitus"]:
            n = n.replace(suffix, "")
        m = re.match(r"(.+?)\s+type\s+(\d+)$", n)
        if m:
            base, num = m.groups()
            return f"type {num} {base}".strip()
        return n.strip()

    @staticmethod
    def _status_for_opposite(asserted: bool) -> VerificationStatus:
        """
        We didn't find the asserted relation, but we did find an opposite one.
          - asserted=True  -> CONTRADICTED (user said X, KG says opposite of X)
          - asserted=False -> SUPPORTED    (user denied X; X is absent;
                                            the opposite is informational only)
        """
        return VerificationStatus.CONTRADICTED if asserted else VerificationStatus.SUPPORTED

    @staticmethod
    def _status_from_assertion(found: bool, asserted: bool, predicate_inverted: bool) -> VerificationStatus:
        """
        Decision matrix for direct (non-opposite) findings:
          - asserted=True  & found=True  -> SUPPORTED
          - asserted=True  & found=False -> NOT_FOUND  (caller may then probe opposite)
          - asserted=False & found=True  -> CONTRADICTED  (user denied, KG affirms)
          - asserted=False & found=False -> SUPPORTED    (absence is what user said)
        """
        if found and asserted:
            return VerificationStatus.SUPPORTED
        if found and not asserted:
            return VerificationStatus.CONTRADICTED
        if not found and not asserted:
            return VerificationStatus.SUPPORTED
        return VerificationStatus.NOT_FOUND

    def _claim_subject(self, drug: Entity, used: Optional[str]) -> str:
        if used and used.lower() != (drug.text or drug.name).lower():
            return f"{drug.name} ({used})"
        return drug.name

    def _render_claim(self, t: ClaimTriple, used_subj: Optional[str] = None,
                      used_obj: Optional[str] = None) -> str:
        if t.asserted:
            verb = _VERB_TEMPLATES.get(t.predicate, t.predicate.lower().replace("_", " "))
        else:
            verb = _NEGATED_VERB_TEMPLATES.get(
                t.predicate, f"does not {_VERB_TEMPLATES.get(t.predicate, t.predicate.lower())}"
            )
        subj = self._claim_subject(t.subject, used_subj)
        obj = self._claim_subject(t.object, used_obj) if used_obj else t.object.name
        return f"{subj} {verb} {obj}"

    def _make_verdict(
        self,
        triple: ClaimTriple,
        status: VerificationStatus,
        kg_result: dict,
        kg_predicate: str,
        used_drug: Optional[str],
        relationship_label: str,
        subj_key: str,
        obj_key: str,
        used_object: Optional[str] = None,
        explanation: Optional[str] = None,
    ) -> ClaimVerification:
        evidence = [
            Evidence(
                source="OptimusKG",
                relationship=relationship_label,
                subject=e.get(subj_key, triple.subject.name),
                object=e.get(obj_key, triple.object.name),
            )
            for e in kg_result.get("evidence", [])[:3]
        ]
        return ClaimVerification(
            claim=self._render_claim(triple, used_subj=used_drug, used_obj=used_object),
            status=status,
            confidence=self._calculate_confidence(triple, kg_result),
            entities=[triple.subject, triple.object],
            evidence=evidence,
            asserted_predicate=triple.predicate,
            evidence_predicate=kg_predicate,
            negated=not triple.asserted,
            explanation=explanation,
        )

    def _not_found(self, t: ClaimTriple) -> ClaimVerification:
        # If the user negated the claim, the absence of an edge in the graph
        # CONFIRMS the denial — that's SUPPORTED, not NOT_FOUND.
        if not t.asserted:
            return ClaimVerification(
                claim=self._render_claim(t),
                status=VerificationStatus.SUPPORTED,
                confidence=0.6,
                entities=[t.subject, t.object],
                evidence=[],
                asserted_predicate=t.predicate,
                evidence_predicate=None,
                negated=True,
                explanation=(
                    f"No {t.predicate.lower().replace('_', ' ')} relationship between "
                    f"{t.subject.text} and {t.object.text} is on record, "
                    f"which is consistent with the assertion."
                ),
            )
        return ClaimVerification(
            claim=self._render_claim(t),
            status=VerificationStatus.NOT_FOUND,
            confidence=0.3,
            entities=[t.subject, t.object],
            evidence=[],
            asserted_predicate=t.predicate,
            evidence_predicate=None,
            negated=False,
        )

    def _calculate_confidence(self, t: ClaimTriple, kg_result: dict) -> float:
        # Mix entity confidence, predicate confidence, and evidence count.
        entity_conf = (t.subject.confidence + t.object.confidence) / 2
        evidence_factor = min(len(kg_result.get("evidence", [])) / 3, 1.0)
        combined = 0.45 * entity_conf + 0.30 * t.confidence + 0.25 * evidence_factor
        return round(min(combined, 1.0), 2)


# Factory function
def get_claim_verifier() -> ClaimVerifier:
    return ClaimVerifier()
