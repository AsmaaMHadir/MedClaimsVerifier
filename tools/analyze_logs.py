"""
Quick analytics over data/verification_log.csv.

Run: mcenv/bin/python tools/analyze_logs.py
Optional: --top N (top NOT_FOUND queries to print, default 20)
"""

from __future__ import annotations

import argparse
import csv
import statistics
from collections import Counter
from pathlib import Path


def parse_rows(csv_path: Path) -> list[dict]:
    if not csv_path.exists():
        return []
    with csv_path.open() as f:
        return list(csv.DictReader(f))


def percent(n: int, d: int) -> str:
    return f"{(100 * n / d):.1f}%" if d else "—"


def report(rows: list[dict], top_n: int) -> None:
    n = len(rows)
    if n == 0:
        print("No log entries yet. Hit /verify a few times.")
        return

    not_found = [r for r in rows if r["had_not_found"] == "1"]
    unknown = [r for r in rows if r["had_unknown"] == "1"]
    used_rx = [r for r in rows if int(r["rxnorm_resolutions"] or 0) > 0]
    latencies = [float(r["processing_time_ms"]) for r in rows if r["processing_time_ms"]]

    print("=" * 64)
    print(f"Verification log analysis  ({n:,} requests)")
    print("=" * 64)
    print(f"NOT_FOUND rate:        {len(not_found)}/{n}  ({percent(len(not_found), n)})")
    print(f"UNKNOWN  rate:         {len(unknown)}/{n}  ({percent(len(unknown), n)})")
    print(f"RxNorm utilization:    {len(used_rx)}/{n}  ({percent(len(used_rx), n)})")
    if latencies:
        latencies.sort()
        p50 = latencies[len(latencies) // 2]
        p95 = latencies[min(int(len(latencies) * 0.95), len(latencies) - 1)]
        print(f"Latency:               p50 {p50:.0f}ms  p95 {p95:.0f}ms  "
              f"max {max(latencies):.0f}ms")
    print()

    # Verdict distribution (each row's verdicts column may be pipe-joined)
    verdict_counts: Counter[str] = Counter()
    for r in rows:
        for v in (r["verdicts"] or "").split("|"):
            if v:
                verdict_counts[v] += 1
    print("Verdict distribution (across all claims, not requests)")
    print("-" * 64)
    total_claims = sum(verdict_counts.values())
    for v, c in verdict_counts.most_common():
        print(f"  {v:<14}  {c:>6}  ({percent(c, total_claims)})")
    print()

    # Top failing queries — dedupe by text_hash
    print(f"Top {top_n} NOT_FOUND queries (by frequency)")
    print("-" * 64)
    nf_counter: Counter[str] = Counter()
    sample: dict[str, str] = {}
    for r in not_found:
        h = r["text_hash"]
        nf_counter[h] += 1
        sample.setdefault(h, r["text"])
    for h, c in nf_counter.most_common(top_n):
        print(f"  ({c:>3}x)  {sample[h][:90]}")
    if not nf_counter:
        print("  (none)")
    print()

    # RxNorm resolutions surfaced
    print("Recent RxNorm resolutions (entity_summary contains '→')")
    print("-" * 64)
    seen_arrows: set[str] = set()
    for r in rows[::-1]:
        for ent in (r["entity_summary"] or "").split(","):
            if "→" in ent and ent not in seen_arrows:
                seen_arrows.add(ent)
                print(f"  {ent}")
                if len(seen_arrows) >= 15:
                    break
        if len(seen_arrows) >= 15:
            break
    if not seen_arrows:
        print("  (none)")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--csv", type=Path, default=Path("data/verification_log.csv"))
    p.add_argument("--top", type=int, default=20)
    args = p.parse_args()
    report(parse_rows(args.csv), args.top)


if __name__ == "__main__":
    main()
