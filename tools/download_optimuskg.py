"""
Download a focused subset of OptimusKG (Zitnik Lab successor to PrimeKG)
for local inspection before committing to a migration.

We pull only the files relevant to MedVerify's verifier path:
  - drug, disease, phenotype node tables (for schema + synonyms / trade_names)
  - drug_disease, drug_phenotype, drug_drug, disease_phenotype edge tables
    (the relations our verifier checks)

After download the script prints, for each edge file, the row count and the
distribution of `relation` sub-types — this is the "is CONTRAINDICATION
actually in there?" sanity check before any further work.

Usage:
    mcenv/bin/python tools/download_optimuskg.py
    mcenv/bin/python tools/download_optimuskg.py --out data/optimuskg
    mcenv/bin/python tools/download_optimuskg.py --files nodes/drug.parquet edges/drug_disease.parquet
    mcenv/bin/python tools/download_optimuskg.py --no-inspect      # just download, skip the relation summary

Requires:
    mcenv/bin/pip install optimuskg polars

Notes:
    - optimuskg's `get_file()` caches under a system-default location; we
      copy the resolved file into `data/optimuskg/` so it sits next to the
      project's other local data.
    - Total download size is roughly a few hundred MB depending on the
      edge tables you ask for.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path
from typing import Iterable


# Subset of OptimusKG relevant to the verifier (Drug × Disease × Phenotype)
DEFAULT_NODE_FILES = [
    "nodes/drug.parquet",
    "nodes/disease.parquet",
    "nodes/phenotype.parquet",
]
DEFAULT_EDGE_FILES = [
    "edges/drug_disease.parquet",      # INDICATION / CONTRAINDICATION / OFF_LABEL_USE
    "edges/drug_phenotype.parquet",    # ADVERSE_DRUG_REACTION / INDICATION / CONTRAINDICATION / OFF_LABEL_USE / ASSOCIATED_WITH
    "edges/drug_drug.parquet",         # SYNERGISTIC_INTERACTION / PARENT
    "edges/disease_phenotype.parquet", # PHENOTYPE_PRESENT
]
DEFAULT_OUT = Path("data/optimuskg")


def _check_deps() -> None:
    missing: list[str] = []
    try:
        import optimuskg  # noqa: F401
    except ImportError:
        missing.append("optimuskg")
    try:
        import polars  # noqa: F401
    except ImportError:
        missing.append("polars")
    if missing:
        print("ERROR: required packages not installed:", ", ".join(missing))
        print(f"  Install with: mcenv/bin/pip install {' '.join(missing)}")
        sys.exit(1)


def download(files: Iterable[str], out_dir: Path) -> list[tuple[str, Path, bool]]:
    import optimuskg

    out_dir.mkdir(parents=True, exist_ok=True)
    results: list[tuple[str, Path, bool]] = []

    for f in files:
        local = out_dir / f
        local.parent.mkdir(parents=True, exist_ok=True)

        if local.exists() and local.stat().st_size > 0:
            results.append((f, local, True))
            print(f"  [cached] {f}  ({local.stat().st_size / 1e6:.1f} MB)")
            continue

        print(f"  [fetch ] {f} ...", flush=True)
        try:
            cached_path = optimuskg.get_file(f)
        except Exception as e:
            print(f"     ! failed: {type(e).__name__}: {e}")
            continue

        # optimuskg returns a path under its own cache dir; copy to our project tree
        shutil.copy2(cached_path, local)
        results.append((f, local, False))
        print(f"     → {local}  ({local.stat().st_size / 1e6:.1f} MB)")

    return results


def inspect(results: list[tuple[str, Path, bool]]) -> None:
    """For each edge file, print row count + distribution of `relation`."""
    import polars as pl

    print()
    print("=" * 72)
    print("Edge-file inspection: rows + `relation` value counts")
    print("=" * 72)

    for name, path, _cached in results:
        if "/edges/" not in name:
            continue
        try:
            df = pl.read_parquet(path)
        except Exception as e:
            print(f"\n  {name}: cannot read ({type(e).__name__}: {e})")
            continue

        print(f"\n  {name}")
        print(f"    rows: {df.height:,}")
        if "relation" in df.columns:
            counts = (
                df.group_by("relation")
                .len()
                .sort("len", descending=True)
            )
            for row in counts.iter_rows(named=True):
                rel = row["relation"]
                n = row["len"]
                print(f"      {rel:<32}  {n:>10,}")
        else:
            print(f"    columns: {df.columns}")


def main() -> None:
    p = argparse.ArgumentParser(description="Download OptimusKG subset for inspection.")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT,
                   help="Output directory (default: data/optimuskg/)")
    p.add_argument("--files", nargs="+", default=None,
                   help="Specific files to fetch (default: 3 node + 4 edge files relevant to verifier)")
    p.add_argument("--no-inspect", action="store_true",
                   help="Download only; skip the relation-count summary")
    args = p.parse_args()

    _check_deps()

    files = args.files or (DEFAULT_NODE_FILES + DEFAULT_EDGE_FILES)
    print(f"Downloading {len(files)} OptimusKG file(s) to {args.out}/")
    print()

    results = download(files, args.out)

    print()
    print("Files in place:")
    total_mb = 0.0
    for name, path, was_cached in results:
        size_mb = path.stat().st_size / 1e6
        total_mb += size_mb
        marker = "cached" if was_cached else "new"
        print(f"  {name:<40}  {size_mb:>8.1f} MB  ({marker})")
    print(f"  {'TOTAL':<40}  {total_mb:>8.1f} MB")

    if not args.no_inspect:
        inspect(results)


if __name__ == "__main__":
    main()
