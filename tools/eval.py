"""
MedVerify evaluation harness.

In-process runner: imports ClaimVerifier directly, loads cases from
`tests/eval/cases.yaml`, runs each, compares actual vs expected, and reports
metrics + per-case results.

Usage:
    mcenv/bin/python tools/eval.py
    mcenv/bin/python tools/eval.py --tag negation         # filter by tag
    mcenv/bin/python tools/eval.py --no-csv               # skip CSV output

What it reports:
  - Raw accuracy (all cases)
  - System accuracy (excludes cases tagged `data_gap`)
  - Per-verdict precision and recall
  - Confusion matrix (expected vs predicted primary verdict)
  - Component accuracy: predicate extraction, negation detection
  - Latency p50, p95, max
  - List of failing cases with diagnostic info
  - CSV of per-case results at tests/eval/results/<timestamp>.csv
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import yaml

# Ensure project root is importable when invoking via `python tools/eval.py`
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.claim_verifier import get_claim_verifier  # noqa: E402
from src.services.gliner_client import get_gliner_client  # noqa: E402
from src.services.knowledge_graph import get_knowledge_graph_service  # noqa: E402
from src.services.drug_normalizer import get_drug_normalizer  # noqa: E402

CASES_PATH = ROOT / "tests" / "eval" / "cases.yaml"
RESULTS_DIR = ROOT / "tests" / "eval" / "results"


# =============================================================================
# Loading & matching
# =============================================================================

def load_cases(path: Path = CASES_PATH) -> list[dict]:
    with path.open() as f:
        cases = yaml.safe_load(f) or []
    if not isinstance(cases, list):
        raise ValueError(f"Expected list of cases at {path}, got {type(cases)}")
    return cases


def matches_single(claims: list[Any], expected: dict) -> tuple[bool, dict]:
    """
    A single-claim case passes iff at least one claim matches:
      - status == expected.verdict
      - asserted_predicate == expected.asserted_predicate (if specified)
      - negated == expected.negated (if specified)

    Returns (passed, primary_match_dict_or_first_claim).
    """
    target_verdict = expected.get("verdict")
    target_pred = expected.get("asserted_predicate")
    target_neg = expected.get("negated")

    # First pass: exact match across all specified fields
    for c in claims:
        c_verdict = getattr(c.status, "value", c.status)
        if c_verdict != target_verdict:
            continue
        if target_pred is not None and c.asserted_predicate != target_pred:
            continue
        if target_neg is not None and bool(c.negated) != bool(target_neg):
            continue
        return True, _claim_to_dict(c)

    # No match — return the first claim as the diagnostic primary
    if claims:
        return False, _claim_to_dict(claims[0])
    return False, {"status": "—", "asserted_predicate": None, "negated": None, "claim": ""}


def matches_multi(claims: list[Any], expected: dict) -> tuple[bool, dict]:
    """
    Multi-claim case: the multisets of (verdict, predicate) in the response must
    contain every expected (verdict, predicate) pair from `verdicts_any` and
    `asserted_predicates_any` (paired by index).
    """
    expected_verdicts = expected.get("verdicts_any", [])
    expected_preds = expected.get("asserted_predicates_any", [None] * len(expected_verdicts))
    expected_pairs = list(zip(expected_verdicts, expected_preds))

    produced_pairs = [
        (getattr(c.status, "value", c.status), c.asserted_predicate)
        for c in claims
    ]

    # For each expected (verdict, predicate), there must be a distinct claim that satisfies it
    remaining = list(produced_pairs)
    matched = 0
    for ev, ep in expected_pairs:
        for i, (pv, pp) in enumerate(remaining):
            if pv == ev and (ep is None or pp == ep):
                remaining.pop(i)
                matched += 1
                break

    passed = matched == len(expected_pairs)
    summary = {
        "expected_pairs": expected_pairs,
        "produced_pairs": produced_pairs,
    }
    return passed, summary


def _claim_to_dict(c: Any) -> dict:
    return {
        "claim": c.claim,
        "status": getattr(c.status, "value", c.status),
        "asserted_predicate": c.asserted_predicate,
        "evidence_predicate": c.evidence_predicate,
        "negated": c.negated,
        "evidence_count": len(c.evidence),
    }


# =============================================================================
# Metrics
# =============================================================================

def percent(n: int, d: int) -> str:
    return f"{(100*n/d):.1f}%" if d else "—"


def compute_metrics(rows: list[dict]) -> dict:
    raw_total = len(rows)
    raw_pass = sum(1 for r in rows if r["passed"])

    sys_rows = [r for r in rows if "data_gap" not in r["tags"]]
    sys_total = len(sys_rows)
    sys_pass = sum(1 for r in sys_rows if r["passed"])

    # Confusion matrix: only single-claim cases (multi cases use bag matching)
    confusion: dict[str, Counter] = defaultdict(Counter)
    for r in rows:
        if r.get("multi"):
            continue
        confusion[r["expected_verdict"] or "—"][r["predicted_verdict"] or "—"] += 1

    # Per-verdict precision and recall
    verdicts = ["SUPPORTED", "CONTRADICTED", "NOT_FOUND", "PARTIAL", "UNKNOWN"]
    pr: dict[str, dict[str, float]] = {}
    for v in verdicts:
        tp = sum(1 for r in rows if not r.get("multi")
                 and r["expected_verdict"] == v and r["predicted_verdict"] == v)
        fp = sum(1 for r in rows if not r.get("multi")
                 and r["expected_verdict"] != v and r["predicted_verdict"] == v)
        fn = sum(1 for r in rows if not r.get("multi")
                 and r["expected_verdict"] == v and r["predicted_verdict"] != v)
        precision = tp / (tp + fp) if (tp + fp) else None
        recall = tp / (tp + fn) if (tp + fn) else None
        pr[v] = {"precision": precision, "recall": recall, "tp": tp, "fp": fp, "fn": fn}

    # Component accuracy: predicate + negation, when expected was specified
    pred_total = pred_correct = 0
    neg_total = neg_correct = 0
    for r in rows:
        if r.get("multi"):
            continue
        if r["expected_predicate"] is not None:
            pred_total += 1
            if r["predicted_predicate"] == r["expected_predicate"]:
                pred_correct += 1
        if r["expected_negated"] is not None:
            neg_total += 1
            if bool(r["predicted_negated"]) == bool(r["expected_negated"]):
                neg_correct += 1

    latencies = sorted(r["latency_ms"] for r in rows if r["latency_ms"] is not None)
    p50 = latencies[len(latencies) // 2] if latencies else 0
    p95_idx = max(0, int(len(latencies) * 0.95) - 1) if latencies else 0
    p95 = latencies[p95_idx] if latencies else 0

    return {
        "raw": {"pass": raw_pass, "total": raw_total},
        "sys": {"pass": sys_pass, "total": sys_total},
        "confusion": confusion,
        "pr": pr,
        "predicate": {"correct": pred_correct, "total": pred_total},
        "negation": {"correct": neg_correct, "total": neg_total},
        "latency": {"p50": p50, "p95": p95, "max": max(latencies) if latencies else 0},
    }


# =============================================================================
# Reporting
# =============================================================================

def render_report(rows: list[dict], metrics: dict, elapsed_s: float) -> str:
    out: list[str] = []
    add = out.append

    add("=" * 76)
    add(f"MedVerify eval · {len(rows)} cases · in-process · {elapsed_s:.1f}s")
    add("=" * 76)
    raw = metrics["raw"]; sys_ = metrics["sys"]
    add(f"Raw accuracy:        {raw['pass']}/{raw['total']}  ({percent(raw['pass'], raw['total'])})")
    add(f"System accuracy:     {sys_['pass']}/{sys_['total']}  "
        f"({percent(sys_['pass'], sys_['total'])})   [excludes data_gap]")
    add("")

    add("Per-verdict precision / recall  (single-claim cases only)")
    add("-" * 76)
    add(f"  {'verdict':<14} {'precision':>10} {'recall':>10} {'tp':>5} {'fp':>5} {'fn':>5}")
    for v, m in metrics["pr"].items():
        p = "—" if m["precision"] is None else f"{m['precision']:.2f}"
        r = "—" if m["recall"] is None else f"{m['recall']:.2f}"
        add(f"  {v:<14} {p:>10} {r:>10} {m['tp']:>5} {m['fp']:>5} {m['fn']:>5}")
    add("")

    add("Confusion matrix  (rows = expected, cols = predicted; single-claim cases)")
    add("-" * 76)
    cols = ["SUPPORTED", "CONTRADICTED", "NOT_FOUND", "PARTIAL", "UNKNOWN"]
    add("                   " + "".join(f"{c[:10]:>11}" for c in cols))
    for ev in cols:
        row = metrics["confusion"].get(ev, Counter())
        add(f"  exp {ev:<13} " + "".join(f"{row.get(c, 0):>11}" for c in cols))
    add("")

    add("Component accuracy")
    add("-" * 76)
    p = metrics["predicate"]; n = metrics["negation"]
    add(f"  Predicate extraction: {p['correct']}/{p['total']}  ({percent(p['correct'], p['total'])})")
    add(f"  Negation detection:   {n['correct']}/{n['total']}  ({percent(n['correct'], n['total'])})")
    add("")

    add(f"Latency: p50 {metrics['latency']['p50']:.0f}ms · "
        f"p95 {metrics['latency']['p95']:.0f}ms · "
        f"max {metrics['latency']['max']:.0f}ms")
    add("")

    failures = [r for r in rows if not r["passed"]]
    add(f"Failures ({len(failures)})")
    add("-" * 76)
    for r in failures:
        gap = " [data_gap]" if "data_gap" in r["tags"] else ""
        if r.get("multi"):
            add(f"  ✗ {r['id']:<26}{gap}")
            add(f"    \"{r['text'][:80]}\"")
            add(f"    expected pairs: {r['extra'].get('expected_pairs')}")
            add(f"    produced pairs: {r['extra'].get('produced_pairs')}")
        else:
            add(f"  ✗ {r['id']:<26}{gap}  "
                f"exp={r['expected_verdict']:<13}  got={r['predicted_verdict'] or '—':<13}  "
                f"pred=({r['expected_predicate']} → {r['predicted_predicate']})")
            add(f"    \"{r['text'][:80]}\"")
    if not failures:
        add("  (none)")
    return "\n".join(out)


def write_csv(rows: list[dict], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "id", "text", "tags", "passed",
        "expected_verdict", "predicted_verdict",
        "expected_predicate", "predicted_predicate",
        "expected_negated", "predicted_negated",
        "evidence_count", "claim_text", "latency_ms", "multi", "notes",
    ]
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow({
                **r,
                "tags": ",".join(r["tags"]),
                "claim_text": r.get("claim_text", ""),
            })


# =============================================================================
# Main
# =============================================================================

async def run_one(verifier, case: dict) -> dict:
    text = case["text"]
    expected = case.get("expected", {})
    tags = case.get("tags", []) or []
    multi = "multi_claim" in tags or "verdicts_any" in expected

    t0 = time.time()
    try:
        claims = await verifier.verify_text(text)
        latency = (time.time() - t0) * 1000
    except Exception as e:
        latency = (time.time() - t0) * 1000
        return {
            "id": case["id"], "text": text, "tags": tags,
            "passed": False, "multi": multi,
            "expected_verdict": expected.get("verdict"),
            "predicted_verdict": "ERROR",
            "expected_predicate": expected.get("asserted_predicate"),
            "predicted_predicate": None,
            "expected_negated": expected.get("negated"),
            "predicted_negated": None,
            "evidence_count": 0,
            "claim_text": "",
            "latency_ms": round(latency, 1),
            "notes": f"EXCEPTION: {e}",
            "extra": {},
        }

    if multi:
        passed, summary = matches_multi(claims, expected)
        primary = _claim_to_dict(claims[0]) if claims else {
            "claim": "", "status": "—", "asserted_predicate": None,
            "evidence_predicate": None, "negated": None, "evidence_count": 0,
        }
        return {
            "id": case["id"], "text": text, "tags": tags,
            "passed": passed, "multi": True,
            "expected_verdict": None,
            "predicted_verdict": primary["status"],
            "expected_predicate": None,
            "predicted_predicate": primary["asserted_predicate"],
            "expected_negated": None,
            "predicted_negated": primary["negated"],
            "evidence_count": primary["evidence_count"],
            "claim_text": primary["claim"],
            "latency_ms": round(latency, 1),
            "notes": case.get("notes", ""),
            "extra": summary,
        }

    passed, primary = matches_single(claims, expected)
    return {
        "id": case["id"], "text": text, "tags": tags,
        "passed": passed, "multi": False,
        "expected_verdict": expected.get("verdict"),
        "predicted_verdict": primary["status"],
        "expected_predicate": expected.get("asserted_predicate"),
        "predicted_predicate": primary["asserted_predicate"],
        "expected_negated": expected.get("negated"),
        "predicted_negated": primary["negated"],
        "evidence_count": primary["evidence_count"],
        "claim_text": primary["claim"],
        "latency_ms": round(latency, 1),
        "notes": case.get("notes", ""),
        "extra": {},
    }


async def main_async(args) -> int:
    cases = load_cases(args.cases)
    if args.tag:
        cases = [c for c in cases if args.tag in (c.get("tags") or [])]
        print(f"Filtering by tag '{args.tag}' → {len(cases)} cases")

    if not cases:
        print("No cases to run.")
        return 0

    print(f"Loading services and warming model (one-time GLiNER cold start)…")
    verifier = get_claim_verifier()
    # Trigger model load up front so the first case doesn't pay the cost
    _ = await verifier.extractor.health_check()

    print(f"Running {len(cases)} case(s)…")
    t0 = time.time()
    rows = []
    for i, case in enumerate(cases, 1):
        if i % 10 == 0 or i == len(cases):
            print(f"  ... {i}/{len(cases)}")
        row = await run_one(verifier, case)
        rows.append(row)
    elapsed = time.time() - t0

    metrics = compute_metrics(rows)
    print()
    print(render_report(rows, metrics, elapsed))

    if not args.no_csv:
        ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
        csv_path = RESULTS_DIR / f"results_{ts}.csv"
        write_csv(rows, csv_path)
        print(f"\nPer-case results written to {csv_path}")

    # Cleanly close shared resources
    try:
        await verifier.extractor.close()
        await verifier.kg.close()
        await verifier.drug_normalizer.close()
    except Exception:
        pass

    raw_pass_rate = metrics["raw"]["pass"] / max(metrics["raw"]["total"], 1)
    return 0 if raw_pass_rate >= args.fail_under else 1


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--cases", type=Path, default=CASES_PATH)
    p.add_argument("--tag", type=str, default=None, help="Filter cases by tag")
    p.add_argument("--no-csv", action="store_true")
    p.add_argument("--fail-under", type=float, default=0.0,
                   help="Exit non-zero if raw accuracy is below this fraction")
    args = p.parse_args()
    sys.exit(asyncio.run(main_async(args)))


if __name__ == "__main__":
    main()
