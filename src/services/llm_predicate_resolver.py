"""
LLM fallback for predicate (verb intent) extraction.

Scope (deliberately narrow): given a sentence and two entities, identify
which knowledge-graph relation the user is asserting between them. Output is
constrained to a fixed enum + a negation flag — the LLM is a paraphrase
parser, not a knowledge source. It does NOT extract entities, normalize drug
names, query the graph, or invent medical facts.

When the rule-based matcher in `predicates.py` returns NONE, the triple
extractor calls into here. Calls are cached in SQLite (both successes AND
misses) keyed by the predicate-window text + entity types.

Provider support:
  * AWS Bedrock (preferred when AWS_BEARER_TOKEN_BEDROCK is set) — uses the
    Anthropic SDK's `AsyncAnthropicBedrock` client. boto3 picks the bearer
    token up from the environment automatically.
  * Direct Anthropic API — used when ANTHROPIC_API_KEY is set and Bedrock
    isn't configured.

Output is enforced via tool-use with `strict` schema and `tool_choice` —
universally compatible across every Claude version on every provider, no
provider-specific quirks. Using tool_use over `messages.parse()` keeps us
working on legacy Bedrock model IDs (e.g. Sonnet 4 from May 2025).
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from loguru import logger

from src.config.settings import get_settings


DEFAULT_DB_PATH = Path("data/drug_normalization.sqlite")  # share the file


# Predicate enum kept in one place
ALLOWED_LABELS = [
    "TREATS",
    "CAUSES_SIDE_EFFECT",
    "CONTRAINDICATED_FOR",
    "INTERACTS_WITH",
    "HAS_SYMPTOM",
    "NONE",
]


# Tool definition — strict schema enforces the output shape
_TOOL = {
    "name": "record_predicate",
    "description": (
        "Record the medical relationship the user asserts between the "
        "subject and object entities, plus whether the user is denying it."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "predicate": {
                "type": "string",
                "enum": ALLOWED_LABELS,
                "description": "The asserted relationship from the fixed list, or NONE.",
            },
            "negated": {
                "type": "boolean",
                "description": (
                    "True only when the user is DENYING the predicate "
                    "(e.g. 'X does not treat Y', 'no evidence of...'). "
                    "Note: 'is contraindicated in' is itself the predicate "
                    "CONTRAINDICATED_FOR (NOT a negated TREATS)."
                ),
            },
            "confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
                "description": "Self-rated confidence (0..1) in the predicate label.",
            },
            "snippet": {
                "type": "string",
                "description": (
                    "The phrase from the input that signals the predicate "
                    "(for explainability). Empty if NONE."
                ),
            },
        },
        "required": ["predicate", "negated", "confidence", "snippet"],
        "additionalProperties": False,
    },
}


_SYSTEM_PROMPT = """You are a precise medical text parser.

Your single job: given a sentence and two medical entities (subject and object), \
identify which clinical relationship the user is ASSERTING between them, \
choosing from a fixed list. You are NOT a medical knowledge source — you do \
not decide whether the assertion is true or false; you only identify what \
relationship the *user's text* claims, and whether the user is denying it.

Allowed relationships:

  TREATS                  Drug/intervention treats, manages, alleviates, or
                          is indicated for the condition.
                          Examples: "X treats Y", "X is used for Y",
                          "X is indicated for Y", "X manages Y",
                          "Patient on X for Y" (implicit treatment),
                          "Patient takes X for Y", "X for Y" with implicit
                          therapeutic intent.

  CAUSES_SIDE_EFFECT      Drug causes, induces, or produces the symptom or
                          condition (typically as an adverse effect).
                          Examples: "X causes Y", "X may cause Y",
                          "X induces Y", "X leads to Y".

  CONTRAINDICATED_FOR     Drug is unsafe or contraindicated in patients
                          with the condition.
                          Examples: "X is contraindicated in Y",
                          "X should not be used in Y", "avoid X in Y".

  INTERACTS_WITH          The two entities are drugs that interact, are
                          combined, or are co-administered.
                          Examples: "X interacts with Y", "X and Y together",
                          "X co-administered with Y",
                          "Patient takes X and Y" (implicit interaction).

  HAS_SYMPTOM             Condition presents with, manifests as, or is
                          characterized by the symptom.
                          Examples: "X presents with Y", "X manifests as Y",
                          "Patients with X complain of Y".

  NONE                    The text does NOT clearly assert any of the above.
                          Use this if the relationship is ambiguous or the
                          entities are merely mentioned without a clear
                          relational claim.

Negation:
  Set `negated: true` ONLY when the user denies the predicate (e.g.
  "X does not treat Y", "no evidence X causes Y"). The phrase
  "is contraindicated in" is the predicate CONTRAINDICATED_FOR itself —
  do NOT mark it as a negated TREATS.

Confidence:
  0.95 = unambiguous wording. 0.7 = inferred (e.g. "patient on X for Y").
  Below 0.6 = genuinely uncertain; downstream will treat as NONE.

Always respond by calling the `record_predicate` tool with your answer."""


# ---------- result type used by callers ----------

@dataclass
class LLMResolution:
    predicate: str
    negated: bool
    confidence: float
    snippet: str
    source: str  # 'bedrock' | 'anthropic' | 'llm_cache' | 'disabled' | 'error'


# ---------- SQLite cache ----------


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_predicate (
            cache_key      TEXT PRIMARY KEY,
            predicate      TEXT NOT NULL,
            negated        INTEGER NOT NULL,
            confidence     REAL NOT NULL,
            snippet        TEXT,
            text_window    TEXT,
            subj_text      TEXT,
            obj_text       TEXT,
            subj_type      TEXT,
            obj_type       TEXT,
            resolved_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


def _make_key(text_window: str, subj_text: str, obj_text: str,
              subj_type: str, obj_type: str) -> str:
    canonical = "|".join([
        " ".join(text_window.lower().split()),
        subj_text.lower().strip(),
        obj_text.lower().strip(),
        subj_type,
        obj_type,
    ])
    return hashlib.sha1(canonical.encode("utf-8")).hexdigest()


# ---------- resolver ----------


class LLMPredicateResolver:
    """Cache-first LLM predicate fallback. Safe to share across requests."""

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        api_key: Optional[str] = None,
        bedrock_token: Optional[str] = None,
        aws_region: Optional[str] = None,
        bedrock_model: Optional[str] = None,
        anthropic_model: Optional[str] = None,
        timeout: Optional[float] = None,
        min_confidence: Optional[float] = None,
        enabled: Optional[bool] = None,
    ):
        settings = get_settings()
        self._db_path = db_path
        self._conn = _connect(db_path)
        self._lock = asyncio.Lock()
        self._client = None  # lazy

        self._api_key = api_key if api_key is not None else settings.anthropic_api_key
        self._bedrock_token = (
            bedrock_token if bedrock_token is not None else settings.aws_bearer_token_bedrock
        )
        self._aws_region = aws_region or settings.aws_region
        self._bedrock_model = bedrock_model or settings.bedrock_model
        self._anthropic_model = anthropic_model or settings.llm_model
        self._timeout = timeout if timeout is not None else settings.llm_timeout_seconds
        self._min_confidence = (
            min_confidence if min_confidence is not None else settings.llm_min_confidence
        )

        # Bedrock takes precedence if a token + model are configured.
        if self._bedrock_token and self._bedrock_model:
            self._mode = "bedrock"
            self._model = self._bedrock_model
            self._source_label = "bedrock"
        elif self._api_key:
            self._mode = "anthropic"
            self._model = self._anthropic_model
            self._source_label = "anthropic"
        else:
            self._mode = "disabled"
            self._model = ""
            self._source_label = "disabled"

        cfg_enabled = enabled if enabled is not None else settings.llm_fallback_enabled
        self._enabled = bool(cfg_enabled and self._mode != "disabled")

        if cfg_enabled and self._mode == "disabled":
            logger.info(
                "LLM predicate fallback flag is ON but neither AWS_BEARER_TOKEN_BEDROCK "
                "(+ BEDROCK_MODEL) nor ANTHROPIC_API_KEY is set; fallback disabled."
            )
        elif self._enabled:
            logger.info(
                f"LLM predicate fallback enabled via {self._mode} (model={self._model}, "
                f"region={self._aws_region if self._mode == 'bedrock' else 'n/a'})"
            )

    @property
    def enabled(self) -> bool:
        return self._enabled

    async def close(self) -> None:
        try:
            self._conn.close()
        except Exception:
            pass
        if self._client is not None:
            try:
                await self._client.close()
            except Exception:
                pass

    # -- cache primitives --

    def _cache_get(self, key: str) -> Optional[LLMResolution]:
        row = self._conn.execute(
            "SELECT predicate, negated, confidence, snippet "
            "FROM llm_predicate WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        return LLMResolution(
            predicate=row[0],
            negated=bool(row[1]),
            confidence=float(row[2]),
            snippet=row[3] or "",
            source="llm_cache",
        )

    def _cache_put(self, key: str, res: LLMResolution,
                   text_window: str, subj_text: str, obj_text: str,
                   subj_type: str, obj_type: str) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO llm_predicate
                (cache_key, predicate, negated, confidence, snippet,
                 text_window, subj_text, obj_text, subj_type, obj_type, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                key, res.predicate, int(res.negated), res.confidence, res.snippet,
                text_window, subj_text, obj_text, subj_type, obj_type,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()

    # -- LLM call --

    def _get_client(self):
        if self._client is not None:
            return self._client
        if self._mode == "bedrock":
            # boto3 reads AWS_BEARER_TOKEN_BEDROCK from os.environ; bridge from
            # the Settings-loaded value so this works whether the env var is
            # exported in the shell or only present in .env.
            import os
            if not os.environ.get("AWS_BEARER_TOKEN_BEDROCK"):
                os.environ["AWS_BEARER_TOKEN_BEDROCK"] = self._bedrock_token
            if not os.environ.get("AWS_REGION"):
                os.environ["AWS_REGION"] = self._aws_region

            from anthropic import AsyncAnthropicBedrock
            self._client = AsyncAnthropicBedrock(
                aws_region=self._aws_region,
                timeout=self._timeout,
            )
        elif self._mode == "anthropic":
            from anthropic import AsyncAnthropic
            self._client = AsyncAnthropic(
                api_key=self._api_key,
                timeout=self._timeout,
            )
        else:
            raise RuntimeError("LLM resolver is disabled — no client to build.")
        return self._client

    async def _call_llm(
        self,
        text: str,
        subj_text: str, subj_type: str,
        obj_text: str, obj_type: str,
    ) -> Optional[dict]:
        client = self._get_client()
        user = (
            f"Sentence: {text!r}\n"
            f"Subject entity: {subj_text!r} (type: {subj_type})\n"
            f"Object entity: {obj_text!r} (type: {obj_type})\n\n"
            f"Identify the relationship the sentence asserts between subject and object."
        )
        try:
            response = await client.messages.create(
                model=self._model,
                max_tokens=300,
                system=_SYSTEM_PROMPT,
                tools=[_TOOL],
                tool_choice={"type": "tool", "name": "record_predicate"},
                messages=[{"role": "user", "content": user}],
            )
        except Exception as e:
            logger.warning(f"LLM predicate call failed: {type(e).__name__}: {e}")
            return None

        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == "record_predicate":
                inp = block.input
                if isinstance(inp, str):
                    try:
                        inp = json.loads(inp)
                    except Exception:
                        return None
                return inp
        logger.warning("LLM response did not include a record_predicate tool call.")
        return None

    # -- public API --

    async def resolve(
        self,
        text: str,
        text_window: str,
        subj_text: str, subj_type: str,
        obj_text: str, obj_type: str,
    ) -> LLMResolution:
        """Resolve the predicate; cache hit returns instantly."""
        if not self._enabled:
            return LLMResolution("NONE", False, 0.0, "", source="disabled")

        key = _make_key(text_window, subj_text, obj_text, subj_type, obj_type)
        async with self._lock:
            cached = self._cache_get(key)
        if cached is not None:
            return cached

        parsed = await self._call_llm(text, subj_text, subj_type, obj_text, obj_type)
        if not parsed:
            return LLMResolution("NONE", False, 0.0, "", source="error")

        # Validate fields defensively
        predicate = str(parsed.get("predicate", "NONE"))
        if predicate not in ALLOWED_LABELS:
            predicate = "NONE"
        try:
            confidence = float(parsed.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        negated = bool(parsed.get("negated", False))
        snippet = str(parsed.get("snippet") or "")

        if confidence < self._min_confidence:
            predicate = "NONE"

        res = LLMResolution(
            predicate=predicate,
            negated=negated,
            confidence=confidence,
            snippet=snippet,
            source=self._source_label,
        )
        async with self._lock:
            self._cache_put(key, res, text_window, subj_text, obj_text, subj_type, obj_type)
        logger.info(
            f"LLM predicate ({self._source_label}): "
            f"({subj_text!r}, {obj_text!r}) -> {res.predicate}"
            f"{'!' if res.negated else ''} (conf={res.confidence})"
        )
        return res


# ---------- singleton ----------

_resolver: Optional[LLMPredicateResolver] = None


def get_llm_predicate_resolver() -> LLMPredicateResolver:
    global _resolver
    if _resolver is None:
        _resolver = LLMPredicateResolver()
    return _resolver
