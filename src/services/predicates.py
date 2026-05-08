"""
Predicate (verb) recognition for medical claim triples.

Two responsibilities:

1. `match_predicate(window)` — given the text BETWEEN a subject and an object,
   identify which knowledge-graph relation the user is asserting (or NONE).

2. `is_negated(window, pre_subject)` — apply NegEx-style heuristics to detect
   whether the assertion is being denied ("no evidence X treats Y").

Why rules first, not an LLM:
  - Medical text uses a small verb vocabulary; ~50 patterns cover ~80% of
    realistic phrasings.
  - Deterministic, debuggable, free, sub-millisecond.
  - LLM fallback is the layer above this for the long tail.

Pattern ordering matters: we run more specific phrases before generic ones
("may cause" before "causes", "is contraindicated in" before "in"), so the
order of patterns within each predicate is significant.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional


# ---------- Predicate vocabulary ----------

# Each entry: (relation_name, list of regex patterns ordered most → least specific).
# Patterns are case-insensitive and word-boundary anchored unless noted.

PREDICATE_PATTERNS: dict[str, list[str]] = {
    "CONTRAINDICATED_FOR": [
        r"\bis\s+contraindicated\s+(in|for|with)\b",
        r"\bare\s+contraindicated\s+(in|for|with)\b",
        r"\bcontraindicated\s+(in|for|with)\b",
        r"\bshould\s+not\s+be\s+(used|given|taken|prescribed)\b",
        r"\bshould\s+never\s+be\s+(used|given|taken|prescribed)\b",
        r"\bmust\s+not\s+be\s+(used|given|taken|prescribed)\b",
        r"\bavoid(ed)?\s+(in|with|when|for)\b",
        r"\b(is\s+)?incompatible\s+with\b",
        r"\bunsafe\s+(in|for|with)\b",
    ],
    "CAUSES_SIDE_EFFECT": [
        r"\bmay\s+cause\b", r"\bcan\s+cause\b", r"\bcould\s+cause\b",
        r"\bsometimes\s+causes?\b",
        r"\bcauses?\b", r"\bcaused\s+by\b",
        r"\binduces?\b", r"\binduced\b",
        r"\bleads?\s+to\b", r"\bled\s+to\b",
        r"\bresults?\s+in\b", r"\bresulted\s+in\b",
        r"\bproduces?\b",
        r"\b(is\s+)?associated\s+with\b",
        r"\bside\s+effect\s+of\b",
        r"\b(may|can|could)\s+(produce|trigger)\b",
        r"\btriggers?\b",
    ],
    "INTERACTS_WITH": [
        r"\binteracts?\s+with\b",
        r"\b(co[\s-]?)?administered\s+with\b",
        r"\b(taken|used|given)\s+(together\s+with|alongside|with)\b",
        r"\bcombined\s+with\b",
        r"\b(combination|coadministration)\s+(with|of)\b",
        r"\band\b",  # weak — "Warfarin and Aspirin together"; only used when both entities are Drugs
    ],
    "HAS_SYMPTOM": [
        r"\bpresents?\s+with\b",
        r"\bmanifests?\s+(as|with)\b",
        r"\b(is\s+)?characteri[sz]ed\s+by\b",
        r"\bcomplains?\s+of\b",
        r"\bpatient(s)?\s+(have|has|with|reports?|describes?)\b",
        r"\bsymptoms?\s+(include|of)\b",
        r"\bsigns?\s+(include|of)\b",
        r"\bshows?\s+signs?\s+of\b",
        r"\b(may|can|could|might)\s+(show|cause|present|manifest)\b",
    ],
    "TREATS": [
        r"\bis\s+used\s+to\s+treat\b", r"\bare\s+used\s+to\s+treat\b",
        r"\bused\s+to\s+treat\b",
        r"\bis\s+used\s+for\b", r"\bare\s+used\s+for\b",
        r"\bis\s+indicated\s+(for|in)\b",
        r"\bare\s+indicated\s+(for|in)\b",
        r"\bindicated\s+(for|in)\b",
        r"\bis\s+prescribed\s+(for|to\s+treat)\b",
        r"\bprescribed\s+(for|to\s+treat)\b",
        r"\btreats?\b", r"\btreating\b", r"\btreated\s+(for|with)\b",
        r"\bmanages?\b", r"\bmanaged\b",
        r"\balleviates?\b", r"\bcontrols?\b",
        r"\b(is\s+)?effective\s+(for|against|in)\b",
        r"\bhelps?\s+with\b", r"\bhelpful\s+for\b",
        # Last-resort weak triggers (only meaningful for Drug→Disease):
        r"\bfor\b",
    ],
}

# Pre-compile patterns once, in the order declared. Within each predicate the
# *first* match wins (so "may cause" beats "cause" when both are present).
_COMPILED: list[tuple[str, re.Pattern[str], int]] = []
for relation, patterns in PREDICATE_PATTERNS.items():
    for i, pat in enumerate(patterns):
        # specificity = (relation_priority, position) — lower = more specific
        # we use it later for tie-breaking
        _COMPILED.append((relation, re.compile(pat, re.IGNORECASE), i))


# ---------- Type-pair compatibility ----------

# Which predicates make sense for a (subject_type, object_type) pair.
# Predicates not listed are not considered.
ALLOWED_PREDICATES: dict[tuple[str, str], list[str]] = {
    # Side effects can be diseases too (e.g. "statins may cause diabetes"),
    # so CAUSES_SIDE_EFFECT belongs alongside TREATS/CONTRAINDICATED_FOR.
    ("Drug", "Disease"):  ["TREATS", "CONTRAINDICATED_FOR", "CAUSES_SIDE_EFFECT"],
    ("Drug", "Symptom"):  ["CAUSES_SIDE_EFFECT", "TREATS"],   # both possible (e.g. Tylenol "treats" headache)
    ("Drug", "Effect"):   ["CAUSES_SIDE_EFFECT"],
    ("Drug", "Drug"):     ["INTERACTS_WITH"],
    ("Disease", "Symptom"): ["HAS_SYMPTOM"],
    ("Disease", "Effect"):  ["HAS_SYMPTOM"],
    # Reversed orderings — the predicate window may sit on either side
    ("Disease", "Drug"):  ["TREATS", "CONTRAINDICATED_FOR"],   # "Diabetes is treated by Metformin"
    ("Symptom", "Drug"):  ["CAUSES_SIDE_EFFECT"],
    ("Symptom", "Disease"): ["HAS_SYMPTOM"],
}


def predicates_for_pair(subject_type: str, object_type: str) -> list[str]:
    return ALLOWED_PREDICATES.get((subject_type, object_type), [])


# ---------- NegEx-style negation ----------

NEGATION_TRIGGERS = [
    # Pre-triggers (appear before the negated phrase)
    r"\bno\s+(evidence|history|signs?|sign|indication|finding(s)?)\s+of\b",
    r"\bnegative\s+for\b",
    r"\brules?\s+out\b", r"\bruled\s+out\b",
    r"\bdenies?\b", r"\bdenied\b",
    r"\bdid\s+not\b", r"\bdoes\s+not\b", r"\bdo\s+not\b",
    r"\bdidn'?t\b", r"\bdoesn'?t\b", r"\bdon'?t\b",
    r"\bnever\b",
    r"\bwithout\b",
    r"\bcannot\b", r"\bcan'?t\b",
    r"\bnot\b",
    r"\bno\b",
    r"\babsent\b", r"\babsence\s+of\b",
    r"\bunable\s+to\b",
]
_NEGATION_PATTERNS = [re.compile(t, re.IGNORECASE) for t in NEGATION_TRIGGERS]

# Conjunctions that *terminate* a negation scope. e.g. "no headache, but takes Tylenol".
SCOPE_TERMINATORS = [r"\bbut\b", r"\bhowever\b", r"\balthough\b", r"\byet\b", r"\bexcept\b", r"[.;]"]
_TERMINATOR_PATTERNS = [re.compile(t, re.IGNORECASE) for t in SCOPE_TERMINATORS]


def is_negated(text_window: str, pre_subject_text: str = "") -> bool:
    """
    Heuristic: a triple is negated if a NegEx trigger appears in the predicate
    window OR in the (~6 token) text immediately before the subject, AND no
    scope-terminator (but/however/.) sits between the trigger and the predicate.
    """
    # Check pre-subject context (last ~10 words)
    pre_tail = " ".join(pre_subject_text.split()[-10:])
    candidates = [pre_tail, text_window]
    for region in candidates:
        if not region:
            continue
        # find the rightmost trigger in this region
        last_trigger_end = -1
        for pat in _NEGATION_PATTERNS:
            for m in pat.finditer(region):
                if m.end() > last_trigger_end:
                    last_trigger_end = m.end()
        if last_trigger_end == -1:
            continue
        # check no terminator between trigger and end of region
        tail = region[last_trigger_end:]
        terminated = any(p.search(tail) for p in _TERMINATOR_PATTERNS)
        if not terminated:
            return True
    return False


# ---------- Public API ----------

@dataclass
class PredicateMatch:
    predicate: str          # one of PREDICATE_PATTERNS keys, or "NONE"
    confidence: float       # 0..1; rule-based matches use heuristic scoring
    snippet: str            # the actual matched substring, for explainability
    pattern_index: int      # position within its predicate's pattern list (lower = more specific)


def match_predicate(
    window: str,
    allowed: Optional[list[str]] = None,
) -> PredicateMatch:
    """
    Find the most specific predicate in `window`.

    Args:
        window: Text between the subject and object entities.
        allowed: If given, restrict matching to these predicates. (We use this
                 to disqualify e.g. INTERACTS_WITH when the pair isn't Drug-Drug.)

    Returns: PredicateMatch with predicate="NONE" and confidence=0 if nothing matches.
    """
    if not window or not window.strip():
        return PredicateMatch(predicate="NONE", confidence=0.0, snippet="", pattern_index=0)

    best: Optional[PredicateMatch] = None
    for relation, regex, index in _COMPILED:
        if allowed is not None and relation not in allowed:
            continue
        m = regex.search(window)
        if not m:
            continue
        # Confidence heuristic: more specific patterns (lower index) get higher
        # confidence; the very-weak "for"/"and" patterns sit at the end of their
        # lists and so get the lowest scores.
        max_index = len(PREDICATE_PATTERNS[relation]) - 1
        confidence = round(0.55 + 0.4 * (1 - index / max(max_index, 1)), 2)
        candidate = PredicateMatch(
            predicate=relation,
            confidence=confidence,
            snippet=m.group(0),
            pattern_index=index,
        )
        if best is None or candidate.confidence > best.confidence:
            best = candidate

    return best or PredicateMatch(predicate="NONE", confidence=0.0, snippet="", pattern_index=0)
