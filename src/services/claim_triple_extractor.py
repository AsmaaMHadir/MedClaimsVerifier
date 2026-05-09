"""
Claim triple extraction.

Given (text, entities), produce a list of ClaimTriples that capture:

    (subject, predicate, object, asserted)

Two-stage extraction:

    1. Rule-based predicate matching (fast, deterministic, free) — covers
       the bulk of clinical phrasings.
    2. LLM fallback for the long tail — implicit predicates ("patient takes
       X for Y"), paraphrases the rules don't anticipate, sophisticated
       negation. Only fires when rules return NONE for a candidate pair.

The LLM is a paraphrase parser: its single job is
to identify which relation the user is asserting between two named
entities, from a fixed enum. Cached in SQLite, so repeat phrasings are free.

Algorithm:

    1. Sort entities by start offset.
    2. For every ordered pair (e_i, e_j) where the type combination is
       verifiable (per predicates.ALLOWED_PREDICATES):
         a. Window = text between e_i.end and e_j.start (≤ ~30 tokens).
         b. Try rule-based match restricted to allowed predicates.
         c. If rules match → emit a triple immediately.
         d. If rules return NONE and the LLM fallback is enabled →
            queue this pair for batched LLM resolution.
    3. Resolve queued pairs in parallel via the LLM (each is independent).
    4. For each LLM result whose predicate is allowed and confidence ≥
       threshold, emit a triple.
    5. Deduplicate triples (same subject/object/predicate/asserted).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import List, Optional

from loguru import logger

from src.models.responses import Entity
from src.services.predicates import (
    is_negated,
    match_predicate,
    predicates_for_pair,
)
from src.services.llm_predicate_resolver import (
    LLMPredicateResolver,
    get_llm_predicate_resolver,
)


@dataclass
class ClaimTriple:
    """A structured claim extracted from text."""

    subject: Entity
    predicate: str          # TREATS | CAUSES_SIDE_EFFECT | CONTRAINDICATED_FOR | INTERACTS_WITH | HAS_SYMPTOM | NONE
    object: Entity
    asserted: bool          # False if negated ("no evidence X treats Y")
    confidence: float       # 0..1
    source: str             # "rules" | "llm" | "llm_cache"
    snippet: str            # the predicate-window text that drove the decision

    def key(self) -> tuple:
        return (
            (self.subject.text or "").lower(),
            self.predicate,
            (self.object.text or "").lower(),
            self.asserted,
        )


@dataclass
class _Candidate:
    """A pair that needs LLM resolution after rules returned NONE."""
    subj: Entity
    obj: Entity
    text_window: str
    allowed: List[str]


# Window size cap (in characters) — predicates farther apart than this are
# likely unrelated. Generous enough for "is sometimes used for the treatment of".
_MAX_WINDOW_CHARS = 200


# Canonical (subject_type, object_type) per predicate — what the verifier
# expects when it queries the knowledge graph. Entities written in reverse
# order ("Diabetes is treated with Metformin") are swapped to canonical.
_CANONICAL_DIRECTION: dict[str, tuple[set[str], set[str]]] = {
    "TREATS":              ({"Drug"}, {"Disease", "Symptom", "Effect", "Phenotype"}),
    "CONTRAINDICATED_FOR": ({"Drug"}, {"Disease", "Symptom", "Effect", "Phenotype"}),
    "CAUSES_SIDE_EFFECT":  ({"Drug"}, {"Effect", "Symptom", "Phenotype", "Disease"}),
    "HAS_SYMPTOM":         ({"Disease"}, {"Symptom", "Effect", "Phenotype"}),
    # INTERACTS_WITH is symmetric — no canonicalisation
}


# Confidence threshold below which a rule match is treated as "weak" — these
# matches are demoted to the LLM path when the entity pair crosses a sentence
# boundary, because weak triggers like "for" / "and" frequently belong to a
# different clause than the one the user is asserting about.
_WEAK_RULE_CONFIDENCE = 0.65


def _crosses_sentence_boundary(window: str) -> bool:
    """True if the predicate window plausibly spans separate sentences."""
    for sep in (". ", "; ", ".\n", ";\n", "! ", "? "):
        if sep in window:
            return True
    return False


def _canonicalize(predicate: str, subj: Entity, obj: Entity) -> tuple[Entity, Entity]:
    """
    For directional predicates, swap subject/object when the user wrote them
    in reverse order (e.g. "Diabetes treated with Metformin" emits TREATS but
    has Disease as subject — flip so the verifier sees Drug as subject).
    """
    direction = _CANONICAL_DIRECTION.get(predicate)
    if direction is None:
        return subj, obj
    subj_types, obj_types = direction
    if subj.type in subj_types and obj.type in obj_types:
        return subj, obj
    if obj.type in subj_types and subj.type in obj_types:
        return obj, subj
    # Mismatched types — leave as-is and let the verifier handle the miss
    return subj, obj


class ClaimTripleExtractor:
    """Two-stage extractor: rules → LLM fallback. Safe to share across requests."""

    def __init__(self, llm_resolver: Optional[LLMPredicateResolver] = None):
        self.llm = llm_resolver or get_llm_predicate_resolver()

    async def extract(self, text: str, entities: List[Entity]) -> List[ClaimTriple]:
        if not text or len(entities) < 2:
            return []

        # Keep only entities with offsets — without them we can't determine
        # adjacency or predicate windows. GLiNER always returns offsets.
        positioned = [
            e for e in entities
            if isinstance(e.start, int) and isinstance(e.end, int) and e.end > e.start
        ]
        positioned.sort(key=lambda e: e.start)

        triples: List[ClaimTriple] = []
        seen: set[tuple] = set()
        # Pairs that didn't match a rule — collected for batched LLM resolution
        llm_candidates: List[_Candidate] = []

        for i, subj in enumerate(positioned):
            for j in range(i + 1, len(positioned)):
                obj = positioned[j]

                if obj.start < subj.end:
                    continue
                if subj.negated or obj.negated:
                    continue

                allowed = predicates_for_pair(subj.type, obj.type)
                if not allowed:
                    continue

                window = text[subj.end : obj.start]
                if len(window) > _MAX_WINDOW_CHARS:
                    continue

                pre_subj = text[: subj.start]
                pm = match_predicate(window, allowed=allowed)

                # Weak rule matches across sentence boundaries are usually
                # false positives (e.g. "Started X for hyperlipidemia. Reports
                # muscle pain" matches "for" between X and muscle pain even
                # though "for" actually attaches to hyperlipidemia). Demote to
                # the LLM if available; else skip.
                if (
                    pm.predicate != "NONE"
                    and pm.confidence < _WEAK_RULE_CONFIDENCE
                    and _crosses_sentence_boundary(window)
                ):
                    if self.llm.enabled:
                        llm_candidates.append(
                            _Candidate(subj=subj, obj=obj, text_window=window, allowed=allowed)
                        )
                    continue

                if pm.predicate != "NONE":
                    # Rule hit. Strip the predicate snippet from the window
                    # before NegEx so embedded negation grammar (e.g. "should
                    # not be used in") doesn't double-count.
                    window_for_negex = (
                        window.replace(pm.snippet, " ", 1) if pm.snippet else window
                    )
                    negated = is_negated(window_for_negex, pre_subj)
                    csubj, cobj = _canonicalize(pm.predicate, subj, obj)
                    triple = ClaimTriple(
                        subject=csubj,
                        predicate=pm.predicate,
                        object=cobj,
                        asserted=not negated,
                        confidence=pm.confidence,
                        source="rules",
                        snippet=pm.snippet,
                    )
                    if triple.key() not in seen:
                        seen.add(triple.key())
                        triples.append(triple)
                    continue

                # Rules returned NONE. Defer to LLM fallback if enabled.
                if self.llm.enabled:
                    llm_candidates.append(
                        _Candidate(subj=subj, obj=obj, text_window=window, allowed=allowed)
                    )

        # ---- LLM fallback: resolve all NONE candidates in parallel ----
        if llm_candidates:
            llm_triples = await self._resolve_via_llm(text, llm_candidates)
            for t in llm_triples:
                if t.key() not in seen:
                    seen.add(t.key())
                    triples.append(t)

        if triples:
            logger.info(
                "Extracted %d triple(s): %s"
                % (
                    len(triples),
                    ", ".join(
                        f"({t.subject.text}, {t.predicate}{'!' if not t.asserted else ''}, "
                        f"{t.object.text})[{t.source}]"
                        for t in triples
                    ),
                )
            )
        else:
            logger.info("No claim triples extracted (entities present but no recognised predicate).")

        return triples

    async def _resolve_via_llm(
        self,
        text: str,
        candidates: List[_Candidate],
    ) -> List[ClaimTriple]:
        """Resolve each candidate via the LLM in parallel; emit triples for the hits."""
        async def resolve_one(c: _Candidate):
            return c, await self.llm.resolve(
                text=text,
                text_window=c.text_window,
                subj_text=c.subj.text or c.subj.name,
                subj_type=c.subj.type,
                obj_text=c.obj.text or c.obj.name,
                obj_type=c.obj.type,
            )

        results = await asyncio.gather(
            *(resolve_one(c) for c in candidates),
            return_exceptions=False,
        )

        triples: List[ClaimTriple] = []
        for c, res in results:
            if res.predicate == "NONE":
                continue
            # Defensive: respect the schema's allowed predicates for this pair.
            # The LLM is told about this constraint in the prompt, but enforce
            # at the boundary in case it slips up.
            if res.predicate not in c.allowed:
                logger.debug(
                    f"LLM returned predicate {res.predicate!r} for "
                    f"({c.subj.type}, {c.obj.type}) which only allows {c.allowed}; skipping."
                )
                continue
            csubj, cobj = _canonicalize(res.predicate, c.subj, c.obj)
            triples.append(ClaimTriple(
                subject=csubj,
                predicate=res.predicate,
                object=cobj,
                asserted=not res.negated,
                confidence=res.confidence,
                source=res.source,        # "llm" or "llm_cache"
                snippet=res.snippet or c.text_window.strip(),
            ))
        return triples


# ---------- singleton ----------

_extractor: Optional[ClaimTripleExtractor] = None


def get_claim_triple_extractor() -> ClaimTripleExtractor:
    global _extractor
    if _extractor is None:
        _extractor = ClaimTripleExtractor()
    return _extractor
