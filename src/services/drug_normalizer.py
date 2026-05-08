"""
Drug name normalization via RxNorm.

Resolves brand names and lay aliases (Tylenol, Lipitor, Ozempic, ...) to their
generic ingredient names so the verifier can find them in PrimeKG.

Strategy:
  1. Look up the input in a local SQLite cache. If found, return it.
  2. Hit RxNorm `approximateTerm` to get a top match + confidence score.
  3. Resolve that match's ingredients via `/rxcui/{id}/related?tty=IN`.
  4. Cache the result (success OR negative) and return.

RxNorm is a free public service from NLM/NIH. No API key, ~20 req/s rate limit.
"""

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger


RXNORM_BASE = "https://rxnav.nlm.nih.gov/REST"
DEFAULT_DB_PATH = Path("data/drug_normalization.sqlite")
DEFAULT_TIMEOUT = 5.0  # seconds per HTTP call


@dataclass
class NormalizedDrug:
    """Result of normalizing a drug name via RxNorm."""

    input: str
    canonical: Optional[str]                # primary ingredient (lowercased)
    rxcui: Optional[str]                    # RxNorm concept identifier
    score: Optional[float]                  # approxTerm confidence (0-100)
    ingredients: list[str] = field(default_factory=list)  # all ingredients
    status: str = "RXNORM_MISS"             # RXNORM_RESOLVED | RXNORM_MISS | RXNORM_ERROR
    source: str = "RxNorm"

    @property
    def candidates(self) -> list[str]:
        """All names worth trying against PrimeKG, lowercased and unique."""
        out: list[str] = []
        for name in [self.canonical, *self.ingredients]:
            if name and name not in out:
                out.append(name)
        return out


# ---------- SQLite cache ----------


def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS drug_norm (
            input_lower   TEXT PRIMARY KEY,
            canonical     TEXT,
            rxcui         TEXT,
            score         REAL,
            ingredients   TEXT,        -- comma-separated, lowercased
            status        TEXT NOT NULL,
            resolved_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


# ---------- RxNorm HTTP client ----------


class _RxNormClient:
    def __init__(self, base_url: str = RXNORM_BASE, timeout: float = DEFAULT_TIMEOUT):
        self._base = base_url
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout)

    async def close(self) -> None:
        await self._client.aclose()

    async def approximate_term(self, term: str, max_entries: int = 1) -> Optional[dict]:
        """
        Best fuzzy match for a name. Returns dict with rxcui, name, score
        (0-100, higher = better), or None if no match.
        """
        try:
            r = await self._client.get(
                "/approximateTerm.json",
                params={"term": term, "maxEntries": max_entries},
            )
            r.raise_for_status()
            data = r.json().get("approximateGroup", {}).get("candidate", [])
            if not data:
                return None
            top = data[0]
            return {
                "rxcui": top.get("rxcui"),
                "name": top.get("name"),
                "score": float(top.get("score", 0)),
            }
        except Exception as e:
            logger.warning(f"RxNorm approximateTerm failed for {term!r}: {e}")
            return None

    async def ingredients(self, rxcui: str) -> list[str]:
        """Return all ingredient (tty=IN) names for an rxcui, lowercased."""
        try:
            r = await self._client.get(
                f"/rxcui/{rxcui}/related.json", params={"tty": "IN"}
            )
            r.raise_for_status()
            groups = r.json().get("relatedGroup", {}).get("conceptGroup", []) or []
            names: list[str] = []
            for grp in groups:
                for prop in grp.get("conceptProperties", []) or []:
                    n = (prop.get("name") or "").strip().lower()
                    if n and n not in names:
                        names.append(n)
            return names
        except Exception as e:
            logger.warning(f"RxNorm ingredients failed for rxcui={rxcui}: {e}")
            return []


# ---------- normalizer service ----------


class DrugNormalizer:
    """
    Cache-first drug normalization. Safe to share across requests.
    """

    def __init__(
        self,
        db_path: Path = DEFAULT_DB_PATH,
        rxnorm_base: str = RXNORM_BASE,
        timeout: float = DEFAULT_TIMEOUT,
    ):
        self._db_path = db_path
        self._conn = _connect(db_path)
        self._client = _RxNormClient(rxnorm_base, timeout)
        self._lock = asyncio.Lock()

    async def close(self) -> None:
        await self._client.close()
        try:
            self._conn.close()
        except Exception:
            pass

    # -- cache primitives --

    def _cache_get(self, input_lower: str) -> Optional[NormalizedDrug]:
        row = self._conn.execute(
            "SELECT input_lower, canonical, rxcui, score, ingredients, status FROM drug_norm WHERE input_lower = ?",
            (input_lower,),
        ).fetchone()
        if row is None:
            return None
        ingredients = [s for s in (row[4] or "").split(",") if s]
        return NormalizedDrug(
            input=row[0],
            canonical=row[1],
            rxcui=row[2],
            score=row[3],
            ingredients=ingredients,
            status=row[5],
        )

    def _cache_put(self, nd: NormalizedDrug) -> None:
        self._conn.execute(
            """
            INSERT OR REPLACE INTO drug_norm
                (input_lower, canonical, rxcui, score, ingredients, status, resolved_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                nd.input.lower(),
                nd.canonical,
                nd.rxcui,
                nd.score,
                ",".join(nd.ingredients),
                nd.status,
                datetime.utcnow().isoformat(timespec="seconds"),
            ),
        )
        self._conn.commit()

    # -- public API --

    async def normalize(self, name: str) -> NormalizedDrug:
        """Return a NormalizedDrug for `name`, hitting RxNorm only on cache miss."""
        key = name.strip().lower()
        if not key:
            return NormalizedDrug(input=name, canonical=None, rxcui=None, score=None,
                                  ingredients=[], status="RXNORM_MISS")

        # Cache lookup is sync (sqlite) — fast and serialized via the lock to keep
        # the connection thread-safe under uvloop.
        async with self._lock:
            cached = self._cache_get(key)
        if cached is not None:
            return cached

        # Cache miss → call RxNorm.
        approx = await self._client.approximate_term(key)
        if not approx or not approx.get("rxcui"):
            nd = NormalizedDrug(
                input=name, canonical=None, rxcui=None, score=None,
                ingredients=[], status="RXNORM_MISS",
            )
            async with self._lock:
                self._cache_put(nd)
            logger.info(f"RxNorm miss for {name!r}")
            return nd

        rxcui = str(approx["rxcui"])
        score = approx.get("score")
        top_name = (approx.get("name") or "").lower()

        # Resolve ingredients. If the matched concept is itself an ingredient,
        # /related?tty=IN returns nothing — fall back to the matched name.
        ingredients = await self._client.ingredients(rxcui)
        if not ingredients and top_name:
            ingredients = [top_name]

        canonical = ingredients[0] if ingredients else top_name or None

        nd = NormalizedDrug(
            input=name,
            canonical=canonical,
            rxcui=rxcui,
            score=score,
            ingredients=ingredients,
            status="RXNORM_RESOLVED",
        )
        async with self._lock:
            self._cache_put(nd)
        logger.info(
            f"RxNorm: {name!r} -> {canonical!r} (rxcui={rxcui}, score={score}, "
            f"ingredients={ingredients})"
        )
        return nd


# ---------- singleton factory ----------

_normalizer: Optional[DrugNormalizer] = None


def get_drug_normalizer() -> DrugNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = DrugNormalizer()
    return _normalizer
