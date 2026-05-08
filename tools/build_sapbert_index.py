"""
One-time builder: embeds every :Disease and :Effect node name in OptimusKG with
SapBERT and writes the index to data/sapbert/index_<label>.npz.

Why a separate script: embedding ~30k strings on CPU takes a few minutes; we do
not want this to happen during the first verification request. Run once, ship
the .npz files to wherever the API runs.

Usage:
    source mcenv/bin/activate
    python tools/build_sapbert_index.py                 # both Disease and Effect
    python tools/build_sapbert_index.py --labels Disease
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from pathlib import Path

# Allow running as a script
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from loguru import logger

from src.config.settings import get_settings
from src.services.sapbert_normalizer import get_sapbert_normalizer
from neo4j import AsyncGraphDatabase


async def fetch_names(driver, label: str) -> list[str]:
    query = f"MATCH (n:{label}) WHERE n.name IS NOT NULL RETURN n.name AS name"
    async with driver.session() as session:
        result = await session.run(query)
        rows = [r["name"] async for r in result]
    # Strip + drop empties + dedupe (preserving order)
    seen: set[str] = set()
    out: list[str] = []
    for r in rows:
        n = (r or "").strip()
        if not n or n.lower() in seen:
            continue
        seen.add(n.lower())
        out.append(n)
    return out


async def main(labels: list[str]) -> None:
    settings = get_settings()
    driver = AsyncGraphDatabase.driver(
        settings.neo4j_uri, auth=(settings.neo4j_user, settings.neo4j_password)
    )
    normalizer = get_sapbert_normalizer()

    try:
        for label in labels:
            t0 = time.time()
            names = await fetch_names(driver, label)
            logger.info(f"[:{label}] pulled {len(names):,} unique names from Neo4j "
                        f"in {time.time()-t0:.1f}s")
            if not names:
                logger.warning(f"[:{label}] no names found; skipping")
                continue
            normalizer.build_index(label, names)
    finally:
        await driver.close()
        await normalizer.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--labels",
        nargs="+",
        default=["Disease", "Effect"],
        help="Node labels to index (default: Disease Effect)",
    )
    args = ap.parse_args()
    asyncio.run(main(args.labels))
