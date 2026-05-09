"""
SapBERT-based lay-term → canonical-term normalizer.

Why: OptimusKG stores diseases and phenotypes under canonical clinical names
("myocardial infarction", "hypertension", "dyspnea"). Users often type lay
terms ("heart attack", "high blood pressure", "shortness of breath") that
have no exact-match or substring path to the canonical node. SapBERT
(`cambridgeltl/SapBERT-from-PubMedBERT-fulltext`) is a small encoder
pretrained on UMLS synonym pairs, so semantically equivalent biomedical
terms produce vectors close in cosine distance.

Architecture:
  1. At first use, embed every Disease and Effect node name in OptimusKG
     and persist the (name, vector) index to `data/sapbert_index.npz`.
  2. Per query: embed the user term, find top-k nearest neighbours by
     cosine similarity. If the top match exceeds the threshold, return
     the canonical name; otherwise return None.
  3. Cache lay→canonical mappings in SQLite so repeats are free.

Used by the verifier as a *fallback*: only fires when the Cypher CONTAINS
lookup returns no rows. Cheap, deterministic where the cache is warm.
"""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import numpy as np
from loguru import logger


SAPBERT_MODEL = "cambridgeltl/SapBERT-from-PubMedBERT-fulltext"
DEFAULT_INDEX_DIR = Path("data/sapbert")
DEFAULT_DB_PATH = Path("data/drug_normalization.sqlite")  
DEFAULT_THRESHOLD = 0.77         
DEFAULT_BATCH_SIZE = 64
EMBED_DIM = 768                  # SapBERT outputs 768-dim vectors


# ---------- result type ----------

@dataclass
class CanonicalMatch:
    user_term: str
    canonical: str         # top match's canonical text
    similarity: float      # cosine similarity (0..1 after L2 norm)
    label: str             # "Disease" or "Effect"
    source: str            # 'sapbert' | 'sapbert_cache' | 'disabled' | 'no_match'


# ---------- SQLite cache ----------

def _connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sapbert_norm (
            cache_key   TEXT PRIMARY KEY,   -- lower(user_term) || '|' || label
            user_term   TEXT NOT NULL,
            label       TEXT NOT NULL,
            canonical   TEXT,               -- NULL when no good match
            similarity  REAL,
            resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    conn.commit()
    return conn


# ---------- the normalizer ----------

class SapBERTNormalizer:
    """Cache-first SapBERT lay-term resolver. Safe to share across requests."""

    def __init__(
        self,
        index_dir: Path = DEFAULT_INDEX_DIR,
        db_path: Path = DEFAULT_DB_PATH,
        threshold: float = DEFAULT_THRESHOLD,
    ):
        self._index_dir = index_dir
        self._index_dir.mkdir(parents=True, exist_ok=True)
        self._conn = _connect(db_path)
        self._threshold = threshold
        self._lock = asyncio.Lock()

        # Lazy-loaded
        self._tokenizer = None
        self._model = None
        # In-memory indexes per label: {label: (np.ndarray (N, 768), list[str] of N names)}
        self._index: dict[str, tuple[np.ndarray, list[str]]] = {}

    # ----- lazy model loading -----

    def _load_model(self):
        if self._model is not None:
            return
        logger.info(f"Loading SapBERT: {SAPBERT_MODEL}")
        from transformers import AutoTokenizer, AutoModel
        import torch
        self._torch = torch
        self._tokenizer = AutoTokenizer.from_pretrained(SAPBERT_MODEL)
        self._model = AutoModel.from_pretrained(SAPBERT_MODEL)
        self._model.eval()
        logger.info("SapBERT loaded")

    # ----- embedding -----

    def embed(self, texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> np.ndarray:
        """Return L2-normalised CLS embeddings for `texts`. Shape (N, 768)."""
        self._load_model()
        torch = self._torch
        out_chunks: list[np.ndarray] = []
        # Underlying PubMedBERT-uncased was trained on lowercase tokens, but the
        # SapBERT tokenizer ships with do_lower_case=False — so anything starting
        # with a capital ("Wheezing", "Cataract") tokenises to [UNK] and the CLS
        # vector collapses onto a generic "unknown" embedding. We lowercase
        # explicitly before tokenisation. The index *must* be built with the
        # same convention (rebuild required after this change).
        texts = [(t or "").lower() for t in texts]
        with torch.no_grad():
            for i in range(0, len(texts), batch_size):
                batch = texts[i : i + batch_size]
                toks = self._tokenizer(batch, padding=True, truncation=True,
                                       max_length=64, return_tensors="pt")
                out = self._model(**toks)
                # CLS pooling
                cls = out.last_hidden_state[:, 0, :]
                # L2 normalise so dot product == cosine similarity
                cls = cls / cls.norm(dim=1, keepdim=True).clamp_min(1e-12)
                out_chunks.append(cls.cpu().numpy().astype(np.float32))
        return np.vstack(out_chunks)

    # ----- index build / load -----

    def index_path(self, label: str) -> Path:
        return self._index_dir / f"index_{label.lower()}.npz"

    def is_ready(self, labels: list[str]) -> bool:
        """All requested label indexes are loaded into memory or exist on disk."""
        for lbl in labels:
            if lbl not in self._index and not self.index_path(lbl).exists():
                return False
        return True

    def build_index(self, label: str, names: list[str]) -> None:
        """Embed `names` and persist to disk. Overwrites any existing index for label."""
        if not names:
            logger.warning(f"No names provided for label={label}; skipping")
            return
        unique_names = list(dict.fromkeys(names))   # dedupe preserving order
        logger.info(f"Building SapBERT index for :{label}: {len(unique_names):,} names")
        t0 = time.time()
        vectors = self.embed(unique_names)
        elapsed = time.time() - t0
        path = self.index_path(label)
        np.savez_compressed(path, vectors=vectors, names=np.array(unique_names, dtype=object))
        self._index[label] = (vectors, unique_names)
        logger.info(f"  → {path}  ({path.stat().st_size / 1e6:.1f} MB, {elapsed:.1f}s)")

    def _ensure_loaded(self, label: str) -> bool:
        if label in self._index:
            return True
        path = self.index_path(label)
        if not path.exists():
            return False
        data = np.load(path, allow_pickle=True)
        self._index[label] = (data["vectors"], list(data["names"]))
        logger.info(f"Loaded SapBERT index :{label}  ({len(self._index[label][1]):,} names)")
        return True

    # ----- cache primitives -----

    def _cache_get(self, key: str) -> Optional[CanonicalMatch]:
        row = self._conn.execute(
            "SELECT user_term, canonical, similarity, label FROM sapbert_norm WHERE cache_key = ?",
            (key,),
        ).fetchone()
        if row is None:
            return None
        ut, can, sim, lbl = row
        return CanonicalMatch(
            user_term=ut,
            canonical=can or "",
            similarity=float(sim or 0.0),
            label=lbl,
            source="sapbert_cache",
        )

    def _cache_put(self, key: str, m: CanonicalMatch) -> None:
        self._conn.execute(
            "INSERT OR REPLACE INTO sapbert_norm (cache_key, user_term, label, canonical, similarity, resolved_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (key, m.user_term, m.label, m.canonical, m.similarity,
             datetime.utcnow().isoformat(timespec="seconds")),
        )
        self._conn.commit()

    # ----- public lookup -----

    async def find_canonical(self, term: str, label: str = "Disease",
                             top_k: int = 3) -> Optional[CanonicalMatch]:
        """
        Find the canonical name in the index for `term`. Returns the best
        match if cosine similarity ≥ threshold, otherwise None.
        """
        term_norm = (term or "").strip()
        if not term_norm:
            return None

        cache_key = f"{term_norm.lower()}|{label}"
        async with self._lock:
            cached = self._cache_get(cache_key)
        if cached is not None:
            if not cached.canonical:
                return None
            if cached.similarity < self._threshold:
                return None
            return cached

        if not self._ensure_loaded(label):
            logger.info(f"SapBERT index for :{label} not built; skipping")
            return None

        # Embed the query and compute cosine sim against the index
        q = self.embed([term_norm])[0]                 # (768,)
        vectors, names = self._index[label]
        sims = vectors @ q                              # (N,)
        # Top-1 is enough for the canonical lookup; top_k future-proofs
        top_idx = int(sims.argmax())
        top_sim = float(sims[top_idx])
        top_name = names[top_idx]
        match = CanonicalMatch(
            user_term=term_norm,
            canonical=top_name,
            similarity=top_sim,
            label=label,
            source="sapbert",
        )
        async with self._lock:
            self._cache_put(cache_key, match)

        if top_sim < self._threshold:
            logger.info(f"SapBERT: {term!r} -> {top_name!r} (sim={top_sim:.3f}) below threshold")
            return None
        logger.info(f"SapBERT: {term!r} -> {top_name!r} (sim={top_sim:.3f}) on :{label}")
        return match

    async def close(self):
        try:
            self._conn.close()
        except Exception:
            pass


# ---------- singleton ----------

_normalizer: Optional[SapBERTNormalizer] = None


def get_sapbert_normalizer() -> SapBERTNormalizer:
    global _normalizer
    if _normalizer is None:
        _normalizer = SapBERTNormalizer()
    return _normalizer
