"""
Build a self-contained, ~5K-edge Cypher seed file for the Docker demo Neo4j.

What it produces:
    docker/neo4j-seed/load_demo_subset.cypher

This file is committed to the repo (gitignore exception) so a stranger can run
`make demo` without ever downloading the full OptimusKG parquet (~400 MB).

How it picks the subset:
    - Starts from a hand-curated DEMO_DRUGS list (the drugs that show up in
      the eval suite + the README's screenshot examples).
    - For each, follows TREATS / CONTRAINDICATED_FOR / CAUSES_SIDE_EFFECT /
      INTERACTS_WITH edges in `data/optimuskg/edges/*.parquet`.
    - Closes the disease/effect set transitively.
    - Includes HAS_SYMPTOM edges between the resulting Disease/Effect nodes.

Re-run after data refreshes:
    python scripts/build_demo_subset.py

Pre-req: `python tools/download_optimuskg.py` must have run; this script reads
the parquet files from `data/optimuskg/`. It does NOT need a live Neo4j.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import polars as pl  # noqa: E402

DATA_DIR = ROOT / "data" / "optimuskg"
OUT_FILE = ROOT / "docker" / "neo4j-seed" / "load_demo_subset.cypher"

# Curated set: drugs the README + eval reference. Names come from OptimusKG's
# `name` field (uppercase by convention there).
DEMO_DRUGS = {
    "METFORMIN", "METFORMIN HYDROCHLORIDE",
    "LISINOPRIL", "ASPIRIN", "WARFARIN", "ATORVASTATIN", "OMEPRAZOLE",
    "INSULIN", "INSULIN HUMAN", "INSULIN GLARGINE",
    "ACETAMINOPHEN", "TYLENOL",
    "ALBUTEROL", "CETIRIZINE", "LEVOCETIRIZINE",
    "PSEUDOEPHEDRINE",     # Sudafed
    "PENICILLIN G",
    "AMOXICILLIN",
    "IBUPROFEN",            # Advil / NSAIDs
    "PROPRANOLOL", "METOPROLOL",   # beta blockers
    "PREDNISONE",           # steroids
    "RAMIPRIL", "ENALAPRIL",       # ACE inhibitors
}

# Predicates to include on the Disease/Effect side
EDGE_FILES = {
    "drug_disease.parquet": [
        ("INDICATION", "TREATS", "Disease"),
        ("CONTRAINDICATION", "CONTRAINDICATED_FOR", "Disease"),
    ],
    "drug_phenotype.parquet": [
        ("ADVERSE_DRUG_REACTION", "CAUSES_SIDE_EFFECT", "Effect"),
        ("CONTRAINDICATION", "CONTRAINDICATED_FOR", "Effect"),
        ("INDICATION", "TREATS", "Effect"),
    ],
    "drug_drug.parquet": [
        ("SYNERGISTIC_INTERACTION", "INTERACTS_WITH", "Drug"),
    ],
    "disease_phenotype.parquet": [
        ("PHENOTYPE_PRESENT", "HAS_SYMPTOM", "Effect"),
    ],
}


# --------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------- #


def _load(path: Path) -> pl.DataFrame:
    if not path.exists():
        raise FileNotFoundError(f"Missing {path}. Run tools/download_optimuskg.py first.")
    return pl.read_parquet(path)


def _cypher_str(s) -> str:
    if s is None:
        return "null"
    return "'" + str(s).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _cypher_str_list(values) -> str:
    if not values:
        return "[]"
    return "[" + ",".join(_cypher_str(v) for v in values if v) + "]"


def _node_cypher(label: str, props: dict) -> str:
    """Emit a single MERGE node statement with the verifier-relevant fields."""
    if label == "Drug":
        kept = {
            "id": props["id"],
            "name": props.get("name"),
            "synonyms": props.get("synonyms") or [],
            "trade_names": props.get("trade_names") or [],
        }
        return (
            f"MERGE (n:Drug {{id: {_cypher_str(kept['id'])}}}) "
            f"SET n.name = {_cypher_str(kept['name'])}, "
            f"    n.synonyms = {_cypher_str_list(kept['synonyms'])}, "
            f"    n.trade_names = {_cypher_str_list(kept['trade_names'])};"
        )
    # Disease + Effect share schema (synonym arrays)
    return (
        f"MERGE (n:{label} {{id: {_cypher_str(props['id'])}}}) "
        f"SET n.name = {_cypher_str(props.get('name'))}, "
        f"    n.exact_synonyms = {_cypher_str_list(props.get('exact_synonyms') or [])}, "
        f"    n.related_synonyms = {_cypher_str_list(props.get('related_synonyms') or [])};"
    )


def _edge_cypher(src_label: str, src_id: str,
                 dst_label: str, dst_id: str,
                 rel: str, max_phase: float | None = None) -> str:
    props = ""
    if max_phase is not None:
        props = f" SET r.max_clinical_trial_phase = {max_phase}"
    return (
        f"MATCH (a:{src_label} {{id: {_cypher_str(src_id)}}}), "
        f"(b:{dst_label} {{id: {_cypher_str(dst_id)}}}) "
        f"MERGE (a)-[r:{rel}]->(b){props};"
    )


# --------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------- #


def main() -> None:
    if not DATA_DIR.exists():
        sys.exit(f"❌ {DATA_DIR} missing. Run: python tools/download_optimuskg.py")

    print(f"▸ Loading parquet files from {DATA_DIR}/")
    drug_df    = _load(DATA_DIR / "nodes" / "drug.parquet")
    disease_df = _load(DATA_DIR / "nodes" / "disease.parquet")
    pheno_df   = _load(DATA_DIR / "nodes" / "phenotype.parquet")

    drug_props_by_id: dict[str, dict] = {}
    drug_id_by_name: dict[str, str] = {}
    for row in drug_df.to_dicts():
        pid = row["id"]
        props = row.get("properties") or {}
        nm = (props.get("name") or "").upper()
        drug_props_by_id[pid] = {"id": pid, **props}
        drug_id_by_name[nm] = pid

    disease_props_by_id = {
        row["id"]: {"id": row["id"], **(row.get("properties") or {})}
        for row in disease_df.to_dicts()
    }
    pheno_props_by_id = {
        row["id"]: {"id": row["id"], **(row.get("properties") or {})}
        for row in pheno_df.to_dicts()
    }

    # Resolve the curated drug list to ids (case-insensitive substring fallback)
    seed_drug_ids: set[str] = set()
    for wanted in DEMO_DRUGS:
        wanted_u = wanted.upper()
        if wanted_u in drug_id_by_name:
            seed_drug_ids.add(drug_id_by_name[wanted_u])
            continue
        for nm, did in drug_id_by_name.items():
            if wanted_u in nm or nm in wanted_u:
                seed_drug_ids.add(did)
    print(f"  ▸ Resolved {len(seed_drug_ids)} drug ids from the curated list")

    selected_disease_ids: set[str] = set()
    selected_effect_ids: set[str] = set()
    # Drug set is the seed only — INTERACTS_WITH endpoints are pulled in for
    # the edge but NOT used as new edge sources, otherwise the graph explodes
    # transitively (1.25M edges in the first pass).
    selected_drug_ids: set[str] = set(seed_drug_ids)
    edges: list[tuple[str, str, str, str, str, float | None]] = []

    # Per-(drug, predicate) cap to keep the seed file small and the demo
    # focused on canonical examples instead of every comorbidity row.
    CAP_PER_DRUG_PRED = 8

    print("▸ Walking edges …")
    for fname, rules in EDGE_FILES.items():
        path = DATA_DIR / "edges" / fname
        if not path.exists():
            print(f"  (skip) {path} not present")
            continue
        df = _load(path)
        per_key: dict[tuple[str, str], int] = {}  # (src_id, neo_rel) -> count
        for row in df.to_dicts():
            src, dst = row.get("from"), row.get("to")
            relation = row.get("relation")
            if not src or not dst or not relation:
                continue
            for opt_rel, neo_rel, dst_label in rules:
                if relation != opt_rel:
                    continue
                # Source must be in the seed (no transitive expansion)
                if src not in seed_drug_ids:
                    continue
                # Per-drug-per-predicate cap
                key = (src, neo_rel)
                if per_key.get(key, 0) >= CAP_PER_DRUG_PRED:
                    continue
                # Phase filter for TREATS edges (matches verifier's KG query)
                phase = (row.get("properties") or {}).get("highest_clinical_trial_phase")
                phase_f = float(phase) if phase is not None else None
                if neo_rel == "TREATS" and phase_f is not None and phase_f < 4.0:
                    continue
                # Add the dst node
                if dst_label == "Disease" and dst in disease_props_by_id:
                    selected_disease_ids.add(dst)
                elif dst_label == "Effect" and dst in pheno_props_by_id:
                    selected_effect_ids.add(dst)
                elif dst_label == "Drug" and dst in drug_props_by_id:
                    selected_drug_ids.add(dst)   # endpoint only, not seeded
                src_label = "Drug"
                edges.append((src_label, src, dst_label, dst, neo_rel, phase_f))
                per_key[key] = per_key.get(key, 0) + 1

    # Now add HAS_SYMPTOM edges between selected diseases and selected effects
    # (capped per disease to keep the seed file small).
    pheno_path = DATA_DIR / "edges" / "disease_phenotype.parquet"
    if pheno_path.exists():
        df = _load(pheno_path)
        sym_count: dict[str, int] = {}
        SYM_CAP_PER_DISEASE = 6
        for row in df.to_dicts():
            src, dst = row.get("from"), row.get("to")
            relation = row.get("relation")
            if relation != "PHENOTYPE_PRESENT":
                continue
            if src not in selected_disease_ids:
                continue
            if sym_count.get(src, 0) >= SYM_CAP_PER_DISEASE:
                continue
            if dst not in pheno_props_by_id:
                continue
            selected_effect_ids.add(dst)
            edges.append(("Disease", src, "Effect", dst, "HAS_SYMPTOM", None))
            sym_count[src] = sym_count.get(src, 0) + 1

    print(f"  Drugs:     {len(selected_drug_ids):>5}")
    print(f"  Diseases:  {len(selected_disease_ids):>5}")
    print(f"  Effects:   {len(selected_effect_ids):>5}")
    print(f"  Edges:     {len(edges):>5}")

    # ----- Emit Cypher -----
    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = [
        "// AUTO-GENERATED by scripts/build_demo_subset.py",
        "// Demo subset of OptimusKG for the Docker `make demo` flow.",
        "// Re-run the script to refresh.",
        "",
        "// --- Indexes -----------------------------------------------",
        "CREATE INDEX IF NOT EXISTS FOR (n:Drug)    ON (n.id);",
        "CREATE INDEX IF NOT EXISTS FOR (n:Disease) ON (n.id);",
        "CREATE INDEX IF NOT EXISTS FOR (n:Effect)  ON (n.id);",
        "CREATE INDEX IF NOT EXISTS FOR (n:Drug)    ON (n.name);",
        "CREATE INDEX IF NOT EXISTS FOR (n:Disease) ON (n.name);",
        "CREATE INDEX IF NOT EXISTS FOR (n:Effect)  ON (n.name);",
        "",
        "// --- Drug nodes --------------------------------------------",
    ]
    for did in sorted(selected_drug_ids):
        if did in drug_props_by_id:
            lines.append(_node_cypher("Drug", drug_props_by_id[did]))
    lines.append("")
    lines.append("// --- Disease nodes -----------------------------------------")
    for did in sorted(selected_disease_ids):
        lines.append(_node_cypher("Disease", disease_props_by_id[did]))
    lines.append("")
    lines.append("// --- Effect nodes ------------------------------------------")
    for did in sorted(selected_effect_ids):
        lines.append(_node_cypher("Effect", pheno_props_by_id[did]))
    lines.append("")
    lines.append("// --- Edges -------------------------------------------------")
    for src_label, src_id, dst_label, dst_id, rel, phase in edges:
        # Skip edges whose endpoints aren't in our selected set
        if src_label == "Drug" and src_id not in selected_drug_ids: continue
        if dst_label == "Drug" and dst_id not in selected_drug_ids: continue
        if dst_label == "Disease" and dst_id not in selected_disease_ids: continue
        if dst_label == "Effect" and dst_id not in selected_effect_ids: continue
        lines.append(_edge_cypher(src_label, src_id, dst_label, dst_id, rel, phase))

    OUT_FILE.write_text("\n".join(lines) + "\n")
    size_mb = OUT_FILE.stat().st_size / 1e6
    print(f"\n✅ Wrote {OUT_FILE.relative_to(ROOT)}  ({size_mb:.1f} MB, {len(lines):,} statements)")
    print("   Re-run `make demo` (or `docker compose up`) to load it into the demo Neo4j.")


if __name__ == "__main__":
    main()
