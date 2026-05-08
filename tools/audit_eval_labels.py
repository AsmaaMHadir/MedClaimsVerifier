"""
Audit `tests/eval/cases.yaml` against the current Neo4j (OptimusKG) data.

Why: when we migrated PrimeKG → OptimusKG, the underlying edge coverage shifted:
  - More TREATS edges (incl. Phase 3 trials, now filtered to phase >= 4)
  - 20K real CONTRAINDICATION edges (PrimeKG had ~zero usable)
  - Fewer ADVERSE_DRUG_REACTION edges (574 total)
  - Different node naming ('hypertensive disorder' vs 'hypertension', etc.)

Several `data_gap` tags and expected verdicts were calibrated against PrimeKG
and may no longer reflect what the graph actually contains. Until labels are
true to the data, the eval's "system accuracy" number is meaningless.

What this does:
  For each case:
    1. Extract entities with GLiNER (same as the verifier)
    2. For each entity pair, enumerate all relevant KG edges using the same
       check_* methods the verifier uses (synonym-aware, phase-filtered)
    3. Classify the case:
         OK            — label matches what the data supports
         DROP_GAP      — case has data_gap tag but the data exists; remove tag
         ADD_GAP       — case has no data_gap but the data is missing
         FLIP_TO_X     — expected verdict mismatches what edges exist;
                         consider flipping to verdict X
         ENTITY_MISS   — GLiNER didn't extract the entities the case relies on
         REVIEW        — multi-claim or ambiguous; needs manual look
  Output: tests/eval/audit_report.md  (Markdown drift report)
          tests/eval/audit_report.csv (machine-readable per-case findings)

Usage:
    mcenv/bin/python tools/audit_eval_labels.py
"""

from __future__ import annotations

import asyncio
import csv
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.services.gliner_client import get_gliner_client  # noqa: E402
from src.services.knowledge_graph import get_knowledge_graph_service  # noqa: E402

CASES_PATH = ROOT / "tests" / "eval" / "cases.yaml"
MD_OUT = ROOT / "tests" / "eval" / "audit_report.md"
CSV_OUT = ROOT / "tests" / "eval" / "audit_report.csv"

# Predicate → (kg method name, takes args (subj_text, obj_text))
PREDICATE_TO_METHOD: dict[str, str] = {
    "TREATS":              "check_drug_treats_disease",
    "CONTRAINDICATED_FOR": "check_contraindication",
    "CAUSES_SIDE_EFFECT":  "check_side_effect",
    "INTERACTS_WITH":      "check_drug_interaction",
    "HAS_SYMPTOM":         "check_disease_symptom",
}

# Map predicate → expected canonical (subject_type, object_type) — used to
# choose which entity pair to query.
PREDICATE_DIRECTION: dict[str, tuple[set[str], set[str]]] = {
    "TREATS":              ({"Drug"}, {"Disease", "Symptom", "Effect", "Phenotype"}),
    "CONTRAINDICATED_FOR": ({"Drug"}, {"Disease", "Symptom", "Effect", "Phenotype"}),
    "CAUSES_SIDE_EFFECT":  ({"Drug"}, {"Symptom", "Effect", "Phenotype", "Disease"}),
    "INTERACTS_WITH":      ({"Drug"}, {"Drug"}),
    "HAS_SYMPTOM":         ({"Disease"}, {"Symptom", "Effect", "Phenotype"}),
}

# Opposite relations to probe for contradiction signals
OPPOSITE_PROBES: dict[str, list[str]] = {
    "TREATS":              ["CONTRAINDICATED_FOR", "CAUSES_SIDE_EFFECT"],
    "CONTRAINDICATED_FOR": ["TREATS"],
    "CAUSES_SIDE_EFFECT":  ["TREATS"],
    "INTERACTS_WITH":      [],
    "HAS_SYMPTOM":         [],
}


@dataclass
class Finding:
    case_id: str
    text: str
    expected_verdict: str | None
    expected_predicate: str | None
    negated: bool
    has_data_gap: bool
    is_multi: bool
    entities_extracted: list[str] = field(default_factory=list)
    asserted_edge_found: Optional[str] = None  # description if found, else None
    opposite_edge_found: Optional[str] = None
    classification: str = "REVIEW"
    recommendation: str = ""

    def as_csv_row(self) -> dict:
        return {
            "case_id": self.case_id,
            "text": self.text,
            "expected_verdict": self.expected_verdict or "",
            "expected_predicate": self.expected_predicate or "",
            "negated": str(self.negated),
            "has_data_gap": str(self.has_data_gap),
            "is_multi": str(self.is_multi),
            "entities": ", ".join(self.entities_extracted),
            "asserted_edge_found": self.asserted_edge_found or "",
            "opposite_edge_found": self.opposite_edge_found or "",
            "classification": self.classification,
            "recommendation": self.recommendation,
        }


def load_cases() -> list[dict]:
    return yaml.safe_load(CASES_PATH.read_text()) or []


def _candidate_pairs(entities: list, subj_types: set[str], obj_types: set[str]) -> list[tuple]:
    """All (subject, object) entity pairs whose types fit the predicate direction."""
    pairs = []
    for s in entities:
        for o in entities:
            if s is o:
                continue
            if s.type in subj_types and o.type in obj_types:
                pairs.append((s, o))
            elif o.type in subj_types and s.type in obj_types:
                pairs.append((o, s))
    # dedupe
    seen = set()
    unique = []
    for s, o in pairs:
        k = (s.text.lower(), o.text.lower())
        if k in seen:
            continue
        seen.add(k)
        unique.append((s, o))
    return unique


async def _probe_relation(kg, method_name: str, subj_text: str, obj_text: str) -> Optional[dict]:
    """Run a kg.check_* method; return first evidence dict if found, else None."""
    method = getattr(kg, method_name, None)
    if method is None:
        return None
    try:
        result = await method(subj_text, obj_text)
    except Exception as e:
        return {"_error": f"{type(e).__name__}: {e}"}
    if result.get("found") and result.get("evidence"):
        return result["evidence"][0]
    return None


async def audit_one(case: dict, gliner, kg) -> Finding:
    expected = case.get("expected") or {}
    expected_verdict = expected.get("verdict")
    expected_predicate = expected.get("asserted_predicate")
    negated = bool(expected.get("negated"))
    tags = case.get("tags") or []
    has_data_gap = "data_gap" in tags
    is_multi = "multi_claim" in tags or "verdicts_any" in expected

    finding = Finding(
        case_id=case["id"],
        text=case["text"],
        expected_verdict=expected_verdict,
        expected_predicate=expected_predicate,
        negated=negated,
        has_data_gap=has_data_gap,
        is_multi=is_multi,
    )

    if is_multi:
        finding.classification = "REVIEW"
        finding.recommendation = "Multi-claim — needs manual review against new data"
        return finding

    # 1. Extract entities
    entities = await gliner.extract_entities(case["text"])
    finding.entities_extracted = [f"{e.text}({e.type})" for e in entities]

    # 2. UNKNOWN cases — expect no medical entities
    if expected_verdict == "UNKNOWN":
        if any(e.type in {"Drug", "Disease", "Symptom", "Effect", "Phenotype"} for e in entities):
            finding.classification = "REVIEW"
            finding.recommendation = (
                f"Expected UNKNOWN but GLiNER extracted entities: "
                f"{finding.entities_extracted}. Consider whether label still appropriate."
            )
        else:
            finding.classification = "OK"
            finding.recommendation = "No medical entities extracted; label correct"
        return finding

    # 3. Without an asserted_predicate we can't probe the KG meaningfully
    if not expected_predicate or expected_predicate not in PREDICATE_TO_METHOD:
        finding.classification = "REVIEW"
        finding.recommendation = "No asserted_predicate; cannot probe data"
        return finding

    # 4. Find candidate entity pair for the predicate's direction
    subj_types, obj_types = PREDICATE_DIRECTION[expected_predicate]
    pairs = _candidate_pairs(entities, subj_types, obj_types)
    if not pairs:
        finding.classification = "ENTITY_MISS"
        finding.recommendation = (
            f"GLiNER didn't extract a pair compatible with predicate "
            f"{expected_predicate} (need {subj_types} -> {obj_types}). "
            f"Got: {finding.entities_extracted}"
        )
        return finding

    # 5. Probe the asserted relation across all candidate pairs
    asserted_method = PREDICATE_TO_METHOD[expected_predicate]
    asserted_hit = None
    for subj, obj in pairs:
        ev = await _probe_relation(kg, asserted_method, subj.text, obj.text)
        if ev and "_error" not in ev:
            asserted_hit = (subj, obj, ev)
            break

    # 6. Probe opposite relations across all candidate pairs
    opposite_hit = None
    opposite_pred_used = None
    for opp_pred in OPPOSITE_PROBES.get(expected_predicate, []):
        opp_method = PREDICATE_TO_METHOD[opp_pred]
        for subj, obj in pairs:
            ev = await _probe_relation(kg, opp_method, subj.text, obj.text)
            if ev and "_error" not in ev:
                opposite_hit = (subj, obj, ev)
                opposite_pred_used = opp_pred
                break
        if opposite_hit:
            break

    if asserted_hit:
        s, o, ev = asserted_hit
        finding.asserted_edge_found = (
            f"{s.text}={ev.get('drug') or ev.get('disease') or ev.get('drug1')} "
            f"-{expected_predicate}-> "
            f"{o.text}={ev.get('disease') or ev.get('effect') or ev.get('symptom') or ev.get('drug2')}"
        )
    if opposite_hit:
        s, o, ev = opposite_hit
        finding.opposite_edge_found = (
            f"{opposite_pred_used}: "
            f"{ev.get('drug') or ev.get('disease') or ev.get('drug1')} -> "
            f"{ev.get('disease') or ev.get('condition') or ev.get('effect') or ev.get('drug2')}"
        )

    # 7. Classify drift
    asserted_present = asserted_hit is not None
    opposite_present = opposite_hit is not None

    # Determine the "honest" expected verdict given current data
    # (mirrors the verifier's own decision logic)
    if negated:
        # User denies the predicate
        # Asserted edge present → CONTRADICTED. Asserted absent → SUPPORTED.
        honest_verdict = "CONTRADICTED" if asserted_present else "SUPPORTED"
    else:
        # User affirms the predicate
        if asserted_present:
            honest_verdict = "SUPPORTED"
        elif opposite_present:
            honest_verdict = "CONTRADICTED"
        else:
            honest_verdict = "NOT_FOUND"

    # Classification
    if honest_verdict == expected_verdict:
        if has_data_gap and asserted_present:
            finding.classification = "DROP_GAP"
            finding.recommendation = (
                f"Tagged data_gap but asserted edge exists. Remove data_gap tag."
            )
        elif has_data_gap and not asserted_present and honest_verdict == "NOT_FOUND":
            finding.classification = "OK"
            finding.recommendation = "data_gap tag still accurate (no edge found)"
        else:
            finding.classification = "OK"
            finding.recommendation = "Label matches data"
    else:
        finding.classification = f"FLIP_TO_{honest_verdict}"
        finding.recommendation = (
            f"Expected verdict ({expected_verdict}) does not match what edges exist. "
            f"Honest verdict given current data: {honest_verdict}. "
            f"Either flip the expected verdict, or — if {expected_verdict} is the "
            f"clinical truth and the data is missing — add/keep data_gap tag."
        )
        if has_data_gap:
            finding.recommendation += " (data_gap tag is currently set)"

    return finding


async def main_async() -> None:
    cases = load_cases()
    print(f"Auditing {len(cases)} cases against current Neo4j data...")

    gliner = get_gliner_client()
    await gliner.health_check()  # warm up
    kg = get_knowledge_graph_service()

    findings: list[Finding] = []
    for i, case in enumerate(cases, 1):
        if i % 10 == 0:
            print(f"  ... {i}/{len(cases)}")
        try:
            f = await audit_one(case, gliner, kg)
        except Exception as e:
            f = Finding(
                case_id=case.get("id", "?"),
                text=case.get("text", ""),
                expected_verdict=(case.get("expected") or {}).get("verdict"),
                expected_predicate=(case.get("expected") or {}).get("asserted_predicate"),
                negated=bool((case.get("expected") or {}).get("negated")),
                has_data_gap="data_gap" in (case.get("tags") or []),
                is_multi="multi_claim" in (case.get("tags") or []),
                classification="REVIEW",
                recommendation=f"Audit error: {type(e).__name__}: {e}",
            )
        findings.append(f)

    await gliner.close()
    await kg.close()

    # Summary counts
    summary: dict[str, int] = {}
    for f in findings:
        summary[f.classification] = summary.get(f.classification, 0) + 1

    print("\n=== Audit summary ===")
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        print(f"  {k:<20} {v:>3}")

    # Markdown report
    lines: list[str] = []
    add = lines.append
    add("# Eval Label Audit vs OptimusKG\n")
    add(f"Total cases: **{len(findings)}**\n\n")
    add("## Classifications\n")
    for k, v in sorted(summary.items(), key=lambda x: -x[1]):
        add(f"- **{k}**: {v}")
    add("")

    by_class: dict[str, list[Finding]] = {}
    for f in findings:
        by_class.setdefault(f.classification, []).append(f)

    for cls in ["FLIP_TO_NOT_FOUND", "FLIP_TO_SUPPORTED", "FLIP_TO_CONTRADICTED",
                "DROP_GAP", "ADD_GAP", "ENTITY_MISS", "REVIEW", "OK"]:
        items = by_class.get(cls, [])
        if not items:
            continue
        add(f"\n## {cls}  ({len(items)})\n")
        for f in items:
            add(f"### `{f.case_id}`")
            add(f"- **text**: {f.text!r}")
            add(f"- **expected**: verdict={f.expected_verdict} predicate={f.expected_predicate} "
                f"negated={f.negated} data_gap={f.has_data_gap}")
            add(f"- **entities**: {f.entities_extracted}")
            if f.asserted_edge_found:
                add(f"- **asserted edge in KG**: {f.asserted_edge_found}")
            if f.opposite_edge_found:
                add(f"- **opposite edge in KG**: {f.opposite_edge_found}")
            add(f"- **recommendation**: {f.recommendation}\n")

    MD_OUT.write_text("\n".join(lines) + "\n")
    print(f"\nMarkdown report → {MD_OUT}")

    # CSV
    fields = list(findings[0].as_csv_row().keys())
    with CSV_OUT.open("w", newline="") as f_out:
        w = csv.DictWriter(f_out, fieldnames=fields)
        w.writeheader()
        for f in findings:
            w.writerow(f.as_csv_row())
    print(f"CSV report → {CSV_OUT}")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
