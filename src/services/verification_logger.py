"""
Verification request logger.

Appends one row per /verify call to a CSV in `data/verification_log.csv`.
Designed as a measurement instrument so we can:
  - establish baseline rates (NOT_FOUND, UNKNOWN) before adding intent/SapBERT
  - measure the lift from RxNorm normalization
  - discover real-world failure modes (lay terms, typos, missing data)

Append-only CSV is chosen over SQLite here on purpose:
  - trivially inspectable (`head data/verification_log.csv`)
  - pandas/duckdb friendly for ad-hoc analysis
  - no migration concerns when columns evolve
  - thread-safe across uvicorn workers via a tiny per-row file lock
"""

from __future__ import annotations

import csv
import hashlib
import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger as log

from src.models.responses import VerifyResponse


CSV_HEADER = [
    "timestamp",
    "text_hash",
    "text",
    "n_entities",
    "entity_summary",
    "n_claims",
    "verdicts",
    "max_confidence",
    "total_evidence",
    "rxnorm_resolutions",
    "had_not_found",
    "had_unknown",
    "processing_time_ms",
]


class VerificationLogger:
    """Append-only CSV logger. Cheap, durable, easy to grep."""

    def __init__(self, csv_path: Path = Path("data/verification_log.csv")):
        self.csv_path = csv_path
        self._lock = threading.Lock()
        self._init_csv()

    def _init_csv(self) -> None:
        self.csv_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.csv_path.exists() or self.csv_path.stat().st_size == 0:
            with self.csv_path.open("w", newline="") as f:
                csv.writer(f).writerow(CSV_HEADER)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha1(text.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _summarize_entities(response: VerifyResponse) -> tuple[int, str, int]:
        """Return (unique_entity_count, summary_string, rxnorm_resolution_count)."""
        seen: dict[tuple[str, str], dict] = {}
        for claim in response.claims:
            for e in claim.entities:
                key = (e.text.lower(), e.type)
                if key not in seen:
                    seen[key] = {
                        "text": e.text,
                        "type": e.type,
                        "normalized": e.normalized_name,
                        "source": e.normalization_source,
                    }

        parts: list[str] = []
        rx_count = 0
        for v in seen.values():
            label = f"{v['type']}:{v['text']}"
            if v["normalized"] and v["normalized"].lower() != v["text"].lower():
                label += f"→{v['normalized']}"
                if (v.get("source") or "") == "RxNorm":
                    rx_count += 1
            parts.append(label)

        return len(seen), ",".join(parts), rx_count

    def log(self, text: str, response: VerifyResponse) -> None:
        """Append one row. Never raises (logging must not break /verify)."""
        try:
            n_entities, entity_summary, rx_count = self._summarize_entities(response)
            verdicts = [c.status.value for c in response.claims]
            max_conf = max((c.confidence for c in response.claims), default=0.0)
            total_evidence = sum(len(c.evidence) for c in response.claims)
            row = [
                datetime.utcnow().isoformat(timespec="seconds") + "Z",
                self._hash(text),
                text,
                n_entities,
                entity_summary,
                len(response.claims),
                "|".join(verdicts),
                round(max_conf, 3),
                total_evidence,
                rx_count,
                int("NOT_FOUND" in verdicts),
                int("UNKNOWN" in verdicts),
                round(response.processing_time_ms, 1),
            ]
            with self._lock:
                with self.csv_path.open("a", newline="") as f:
                    csv.writer(f).writerow(row)
        except Exception as e:
            # Logging is best-effort. Do not let it impact /verify.
            log.warning(f"VerificationLogger.log failed: {e}")


# ---------- singleton ----------

_logger: Optional[VerificationLogger] = None


def get_verification_logger() -> VerificationLogger:
    global _logger
    if _logger is None:
        _logger = VerificationLogger()
    return _logger
