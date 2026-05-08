"""
PrimeKG coverage scanner.

Pass 1 over kg.csv:
  - count unique nodes per type
  - sample names per type
  - measure name-length distribution

Pass 2 (in-memory):
  - check exact + substring coverage for a curated list of common lay terms
    across drugs (brand/generic), conditions, and symptoms

Output:
  - human-readable summary to stdout
  - tools/coverage_report.json with the full numeric breakdown
  - tools/lay_term_coverage.csv with per-term hit/miss

Usage:
  mcenv/bin/python tools/scan_kg_coverage.py [--kg-path kg.csv]
"""

from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable


# ---------- curated lay-term test set ----------

LAY_TERMS: dict[str, list[str]] = {
    "drugs_brand": [
        "Tylenol", "Advil", "Motrin", "Aleve", "Benadryl", "Claritin",
        "Zyrtec", "Lipitor", "Plavix", "Nexium", "Prilosec", "Xanax",
        "Adderall", "Sudafed", "Pepto-Bismol", "Tums", "Imodium",
        "Aspirin", "Ozempic", "Wegovy",
    ],
    "drugs_generic": [
        "acetaminophen", "ibuprofen", "naproxen", "diphenhydramine",
        "loratadine", "cetirizine", "atorvastatin", "clopidogrel",
        "esomeprazole", "omeprazole", "alprazolam", "metformin",
        "lisinopril", "amlodipine", "warfarin", "amoxicillin",
        "prednisone", "insulin", "albuterol", "semaglutide",
    ],
    "conditions_lay": [
        "high blood pressure", "diabetes", "type 2 diabetes",
        "heart attack", "stroke", "asthma", "cold", "flu", "covid",
        "migraine", "arthritis", "depression", "anxiety", "cancer",
        "allergies", "high cholesterol", "kidney failure",
        "stomach ulcer", "heartburn", "pneumonia",
    ],
    "conditions_clinical": [
        "hypertension", "diabetes mellitus", "myocardial infarction",
        "cerebrovascular accident", "asthma", "influenza",
        "covid-19", "rheumatoid arthritis", "major depressive disorder",
        "generalized anxiety disorder", "hyperlipidemia",
        "chronic kidney disease", "peptic ulcer disease",
        "gastroesophageal reflux disease", "atrial fibrillation",
    ],
    "symptoms_lay": [
        "headache", "fever", "cough", "wheezing", "sore throat",
        "runny nose", "fatigue", "chest pain", "shortness of breath",
        "dizziness", "nausea", "vomiting", "diarrhea", "rash",
        "itching", "swelling", "chills", "muscle ache", "back pain",
        "stomach ache", "heartburn", "blurred vision", "ringing in ears",
        "numbness", "tingling",
    ],
    "symptoms_clinical": [
        "pyrexia", "dyspnea", "syncope", "vertigo", "myalgia",
        "pruritus", "edema", "tachycardia", "bradycardia", "polyuria",
        "polydipsia", "anorexia", "asthenia", "diaphoresis", "stridor",
    ],
}


# ---------- pass 1: scan ----------

def scan_kg(kg_path: Path) -> dict:
    """One streaming pass; collect unique (type, name) pairs and stats."""
    nodes: dict[str, set[str]] = defaultdict(set)
    relation_counter: Counter[str] = Counter()
    rows = 0

    with kg_path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows += 1
            relation_counter[row["relation"]] += 1
            nodes[row["x_type"]].add(row["x_name"])
            nodes[row["y_type"]].add(row["y_name"])
            if rows % 1_000_000 == 0:
                print(f"  ... scanned {rows:,} rows")

    summary = {
        "total_rows": rows,
        "node_counts": {t: len(names) for t, names in nodes.items()},
        "relation_counts": dict(relation_counter),
        "name_length_stats": {
            t: {
                "median": statistics.median(len(n) for n in names),
                "mean": round(sum(len(n) for n in names) / len(names), 1),
                "max": max(len(n) for n in names),
            }
            for t, names in nodes.items()
        },
        "samples": {t: sorted(list(names))[:10] for t, names in nodes.items()},
    }
    return {"summary": summary, "nodes": nodes}


# ---------- pass 2: lay-term coverage ----------

def normalize(s: str) -> str:
    return " ".join(s.lower().strip().split())


def measure_coverage(
    terms: dict[str, list[str]],
    nodes: dict[str, set[str]],
) -> dict:
    """For each term, check exact and substring match across the relevant
    PrimeKG node types."""

    # Map test category -> which PrimeKG node types are valid targets
    category_targets: dict[str, list[str]] = {
        "drugs_brand": ["drug"],
        "drugs_generic": ["drug"],
        "conditions_lay": ["disease"],
        "conditions_clinical": ["disease"],
        "symptoms_lay": ["effect/phenotype", "phenotype"],
        "symptoms_clinical": ["effect/phenotype", "phenotype"],
    }

    # Pre-normalize every name once per type
    normalized: dict[str, set[str]] = {
        t: {normalize(n) for n in names} for t, names in nodes.items()
    }

    results: dict[str, list[dict]] = {}
    for category, term_list in terms.items():
        target_types = category_targets[category]
        target_pool = set().union(*(normalized.get(t, set()) for t in target_types))
        cat_results = []
        for term in term_list:
            n = normalize(term)
            exact = n in target_pool
            substr_hits = 0
            sample_substr = None
            if not exact:
                for name in target_pool:
                    if n in name:
                        substr_hits += 1
                        if sample_substr is None:
                            sample_substr = name
                        if substr_hits >= 5:
                            break
            cat_results.append({
                "term": term,
                "exact": exact,
                "substring_hits": substr_hits,
                "substring_example": sample_substr,
            })
        results[category] = cat_results
    return results


# ---------- reporting ----------

def percent(n: int, d: int) -> str:
    return f"{(100*n/d):.0f}%" if d else "—"


def report(summary: dict, coverage: dict) -> str:
    lines: list[str] = []
    add = lines.append

    add("=" * 70)
    add("PrimeKG Coverage Report")
    add("=" * 70)
    add(f"Total CSV rows:            {summary['total_rows']:,}")
    add("")

    add("Unique node counts by source type")
    add("-" * 70)
    for t, c in sorted(summary["node_counts"].items(), key=lambda x: -x[1]):
        add(f"  {t:<22}  {c:>10,}  (median name length {summary['name_length_stats'][t]['median']:.0f})")
    add("")

    add("Relation row counts (top 12)")
    add("-" * 70)
    for r, c in sorted(summary["relation_counts"].items(), key=lambda x: -x[1])[:12]:
        add(f"  {r:<35}  {c:>10,}")
    add("")

    add("Sample names per type (first 5)")
    add("-" * 70)
    for t, samples in summary["samples"].items():
        add(f"  {t}:")
        for s in samples[:5]:
            add(f"      {s}")
    add("")

    add("Lay-term coverage")
    add("-" * 70)
    for category, items in coverage.items():
        n = len(items)
        exact = sum(1 for it in items if it["exact"])
        substr = sum(1 for it in items if not it["exact"] and it["substring_hits"] > 0)
        miss = n - exact - substr
        add(f"  {category:<22}  exact {exact}/{n} ({percent(exact, n)})  "
            f"substring {substr}/{n} ({percent(substr, n)})  "
            f"miss {miss}/{n} ({percent(miss, n)})")
    add("")

    add("Per-term breakdown")
    add("-" * 70)
    for category, items in coverage.items():
        add(f"  [{category}]")
        for it in items:
            if it["exact"]:
                tag = "EXACT"
                detail = ""
            elif it["substring_hits"]:
                tag = "FUZZY"
                detail = f"({it['substring_hits']} hits, e.g. \"{it['substring_example']}\")"
            else:
                tag = "MISS "
                detail = ""
            add(f"    {tag}  {it['term']:<32}  {detail}")
        add("")

    return "\n".join(lines)


# ---------- main ----------

def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--kg-path", type=Path, default=Path("kg.csv"))
    p.add_argument("--out-dir", type=Path, default=Path("tools"))
    args = p.parse_args()

    if not args.kg_path.exists():
        raise SystemExit(f"kg file not found: {args.kg_path}")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    print(f"Scanning {args.kg_path} ...")
    scan = scan_kg(args.kg_path)
    summary = scan["summary"]
    nodes = scan["nodes"]

    coverage = measure_coverage(LAY_TERMS, nodes)

    text = report(summary, coverage)
    print()
    print(text)

    # Persist machine-readable artifacts
    (args.out_dir / "coverage_report.json").write_text(
        json.dumps({"summary": summary, "lay_term_coverage": coverage}, indent=2)
    )

    csv_path = args.out_dir / "lay_term_coverage.csv"
    with csv_path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["category", "term", "exact", "substring_hits", "substring_example"])
        for cat, items in coverage.items():
            for it in items:
                w.writerow([cat, it["term"], it["exact"], it["substring_hits"], it["substring_example"] or ""])

    print(f"\nWrote: {args.out_dir/'coverage_report.json'}")
    print(f"Wrote: {csv_path}")


if __name__ == "__main__":
    main()
