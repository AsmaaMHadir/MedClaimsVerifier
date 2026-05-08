"""
OptimusKG → Neo4j importer.

Selective import of the verifier-relevant slice of OptimusKG:
  Nodes:    Drug, Disease, Phenotype  (Phenotype is materialised as :Effect
            in Neo4j to stay schema-compatible with the existing verifier
            Cypher, which queries :Effect for symptoms/side effects.)
  Edges:    DRG-DIS, DRG-PHE, DRG-DRG, DIS-PHE
            Sub-relations are mapped to PrimeKG-compatible relationship
            types so existing verifier queries continue to work:
              INDICATION              -> TREATS
              CONTRAINDICATION        -> CONTRAINDICATED_FOR
              OFF_LABEL_USE           -> OFF_LABEL_FOR
              ADVERSE_DRUG_REACTION   -> CAUSES_SIDE_EFFECT
              ASSOCIATED_WITH         -> ASSOCIATED_WITH (kept as-is)
              SYNERGISTIC_INTERACTION -> INTERACTS_WITH
              PHENOTYPE_PRESENT       -> HAS_SYMPTOM
              PARENT (drug class)     -> skipped

Node properties brought across (when present):
  Drug:    name, synonyms[], trade_names[], cas, unii, is_approved,
           year_of_first_approval, has_been_withdrawn, type, status,
           description
  Disease: name, exact_synonyms[], related_synonyms[], broad_synonyms[],
           narrow_synonyms[], umls_cui, snomed_concept_ids[],
           snomed_full_names[], xrefs[], description, code,
           therapeutic_areas[]
  Effect:  name, exact_synonyms[], related_synonyms[], broad_synonyms[],
           narrow_synonyms[], description, code

Provenance preserved via the `sources_direct` and `sources_indirect` lists
on every edge, so we can later filter by data source if needed.

Usage:
    mcenv/bin/python import_optimuskg_to_neo4j.py \\
        --data-dir data/optimuskg \\
        --neo4j-uri "$NEO4J_URI" \\
        --neo4j-user "$NEO4J_USER" \\
        --neo4j-password "$NEO4J_PASSWORD" \\
        --clear-db
"""

from __future__ import annotations

import argparse
import logging
import time
from collections import Counter
from pathlib import Path
from typing import Iterable

import polars as pl
from neo4j import GraphDatabase


logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Mapping tables: OptimusKG → PrimeKG-compatible Neo4j schema
# ---------------------------------------------------------------------------

NODE_LABEL_MAP: dict[str, str] = {
    "DRG": "Drug",
    "DIS": "Disease",
    "PHE": "Effect",  # PrimeKG calls these :Effect; verifier already queries :Effect
}

# Source/target Neo4j labels per OptimusKG edge label. Used so the MATCH
# clause can take advantage of (:Label, id) indexes — without labels,
# Neo4j falls back to a full database scan, making the import ~1000x slower.
EDGE_LABEL_PAIR: dict[str, tuple[str, str]] = {
    "DRG-DIS": ("Drug",    "Disease"),
    "DRG-PHE": ("Drug",    "Effect"),
    "DRG-DRG": ("Drug",    "Drug"),
    "DIS-PHE": ("Disease", "Effect"),
}

# (edge_label, sub_relation) -> Neo4j relationship type. Anything not listed
# here is skipped (e.g. DRG-DRG PARENT which is a drug-class hierarchy
# unused by the verifier).
EDGE_RELATION_MAP: dict[tuple[str, str], str] = {
    ("DRG-DIS", "INDICATION"):              "TREATS",
    ("DRG-DIS", "CONTRAINDICATION"):        "CONTRAINDICATED_FOR",
    ("DRG-DIS", "OFF_LABEL_USE"):           "OFF_LABEL_FOR",
    ("DRG-PHE", "INDICATION"):              "TREATS",
    ("DRG-PHE", "CONTRAINDICATION"):        "CONTRAINDICATED_FOR",
    ("DRG-PHE", "ADVERSE_DRUG_REACTION"):   "CAUSES_SIDE_EFFECT",
    ("DRG-PHE", "ASSOCIATED_WITH"):         "ASSOCIATED_WITH",
    ("DRG-PHE", "OFF_LABEL_USE"):           "OFF_LABEL_FOR",
    ("DRG-DRG", "SYNERGISTIC_INTERACTION"): "INTERACTS_WITH",
    ("DIS-PHE", "PHENOTYPE_PRESENT"):       "HAS_SYMPTOM",
}


# ---------------------------------------------------------------------------
# Property extraction (one function per node type — the schemas differ)
# ---------------------------------------------------------------------------

def _safe_list(val) -> list:
    if val is None:
        return []
    return [x for x in val if x is not None]


def _safe_str(val) -> str | None:
    if val is None:
        return None
    s = str(val).strip()
    return s or None


def extract_drug_props(props: dict) -> dict:
    return {
        "name": _safe_str(props.get("name")),
        "synonyms": _safe_list(props.get("synonyms")),
        "trade_names": _safe_list(props.get("trade_names")),
        "cas": _safe_str(props.get("chemical_abstracts_service_number")),
        "unii": _safe_str(props.get("unique_ingredient_identifier")),
        "type": _safe_str(props.get("type")),
        "status": _safe_str(props.get("status")),
        "is_approved": props.get("is_approved"),
        "has_been_withdrawn": props.get("has_been_withdrawn"),
        "year_of_first_approval": props.get("year_of_first_approval"),
        "description": _safe_str(props.get("description")),
    }


def extract_disease_props(props: dict) -> dict:
    return {
        "name": _safe_str(props.get("name")),
        "code": _safe_str(props.get("code")),
        "exact_synonyms": _safe_list(props.get("exact_synonyms")),
        "related_synonyms": _safe_list(props.get("related_synonyms")),
        "broad_synonyms": _safe_list(props.get("broad_synonyms")),
        "narrow_synonyms": _safe_list(props.get("narrow_synonyms")),
        "umls_cui": _safe_str(props.get("umls_cui")),
        "snomed_concept_ids": _safe_list(props.get("snomed_concept_ids")),
        "snomed_full_names": _safe_list(props.get("snomed_full_names")),
        "xrefs": _safe_list(props.get("xrefs")),
        "therapeutic_areas": _safe_list(props.get("therapeutic_areas")),
        "description": _safe_str(props.get("description")),
    }


def extract_phenotype_props(props: dict) -> dict:
    return {
        "name": _safe_str(props.get("name")),
        "code": _safe_str(props.get("code")),
        "exact_synonyms": _safe_list(props.get("exact_synonyms")),
        "related_synonyms": _safe_list(props.get("related_synonyms")),
        "broad_synonyms": _safe_list(props.get("broad_synonyms")),
        "narrow_synonyms": _safe_list(props.get("narrow_synonyms")),
        "description": _safe_str(props.get("description")),
    }


NODE_PROP_EXTRACTORS = {
    "Drug": extract_drug_props,
    "Disease": extract_disease_props,
    "Effect": extract_phenotype_props,
}


def extract_edge_props(props: dict, sources: dict | None) -> dict:
    """Edge properties common across edge types + provenance from sources struct."""
    out: dict = {}
    if props is None:
        props = {}
    sources = sources or {}
    out["sources_direct"] = _safe_list(sources.get("direct"))
    out["sources_indirect"] = _safe_list(sources.get("indirect"))
    # Optional drug_disease / drug_phenotype clinical-trial-phase enrichment
    if "highest_clinical_trial_phase" in props and props["highest_clinical_trial_phase"] is not None:
        out["max_clinical_trial_phase"] = float(props["highest_clinical_trial_phase"])
    # interaction_description for DRG-DRG
    desc = props.get("interaction_description")
    if desc:
        out["interaction_description"] = str(desc)[:512]
    return out


# ---------------------------------------------------------------------------
# Importer
# ---------------------------------------------------------------------------


class OptimusKGImporter:
    def __init__(self, uri: str, user: str, password: str, chunk_size: int = 5000):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
        self.chunk_size = chunk_size
        logger.info(f"Connected to Neo4j at {uri[:32]}...")

    def close(self):
        self.driver.close()

    # ----- schema management -----

    def clear_database(self) -> None:
        """
        Wipe the database in two phases (relationships, then nodes), each
        with a tight batch size. Aura caps `dbms.memory.transaction.total.max`
        at ~278 MiB per transaction, and a single 10K-node DETACH DELETE on
        a densely-connected graph (e.g. PrimeKG with 2.4M edges) blows that
        limit. Deleting relationships first lets the second pass do plain
        DELETE on isolated nodes — both phases stay small in memory.
        """
        logger.info("Clearing database...")
        with self.driver.session() as session:
            # Phase 1: delete relationships in 5K-row batches
            phase1_total = 0
            while True:
                rec = session.run(
                    "MATCH ()-[r]->() WITH r LIMIT 5000 DELETE r RETURN count(r) AS n"
                ).single()
                if rec["n"] == 0:
                    break
                phase1_total += rec["n"]
                if phase1_total % 50000 == 0:
                    logger.info(f"  ... deleted {phase1_total:,} relationships")
            logger.info(f"  relationships removed: {phase1_total:,}")

            # Phase 2: delete now-isolated nodes in 5K-row batches
            phase2_total = 0
            while True:
                rec = session.run(
                    "MATCH (n) WITH n LIMIT 5000 DELETE n RETURN count(n) AS n"
                ).single()
                if rec["n"] == 0:
                    break
                phase2_total += rec["n"]
                if phase2_total % 50000 == 0:
                    logger.info(f"  ... deleted {phase2_total:,} nodes")
            logger.info(f"  nodes removed: {phase2_total:,}")
        logger.info("Database cleared")

    def create_indexes(self) -> None:
        logger.info("Creating indexes...")
        with self.driver.session() as session:
            for label in NODE_LABEL_MAP.values():
                session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.id)")
                session.run(f"CREATE INDEX IF NOT EXISTS FOR (n:{label}) ON (n.name)")
            # Full-text index for fuzzy lookup (used by the verifier when
            # falling through name/synonym/trade_name CONTAINS chains)
            for label in NODE_LABEL_MAP.values():
                idx = f"ft_{label.lower()}_lookup"
                # synonyms/trade_names are arrays — Neo4j FT supports list props
                session.run(
                    f"""
                    CREATE FULLTEXT INDEX {idx} IF NOT EXISTS
                    FOR (n:{label}) ON EACH [n.name]
                    """
                )
        logger.info("Indexes ready")

    # ----- node import -----

    def import_nodes(self, parquet_path: Path, optimus_label: str) -> int:
        if optimus_label not in NODE_LABEL_MAP:
            raise ValueError(f"Unknown optimus label {optimus_label}")
        neo_label = NODE_LABEL_MAP[optimus_label]
        extractor = NODE_PROP_EXTRACTORS[neo_label]

        logger.info(f"Loading {parquet_path.name} -> :{neo_label}")
        df = pl.read_parquet(parquet_path)
        rows = df.to_dicts()
        total = len(rows)
        logger.info(f"  {total:,} rows; importing in chunks of {self.chunk_size}")

        # Build batches with extracted top-level properties
        def make_batch(slice_):
            batch = []
            for r in slice_:
                if r.get("label") and r["label"] != optimus_label:
                    continue  # defensive: rare cross-label rows
                node = {"id": r["id"]}
                node.update(extractor(r.get("properties") or {}))
                batch.append(node)
            return batch

        query = f"""
        UNWIND $rows AS row
        MERGE (n:{neo_label} {{id: row.id}})
        SET n += row
        """

        imported = 0
        with self.driver.session() as session:
            for i in range(0, total, self.chunk_size):
                batch = make_batch(rows[i : i + self.chunk_size])
                if not batch:
                    continue
                session.run(query, rows=batch)
                imported += len(batch)
                if imported % 50000 == 0 or imported == total:
                    logger.info(f"    ... {imported:,}/{total:,} :{neo_label} nodes")
        logger.info(f"  done: {imported:,} :{neo_label} nodes")
        return imported

    # ----- edge import -----

    def import_edges(self, parquet_path: Path, edge_label: str) -> dict[str, int]:
        """edge_label is the OptimusKG label (e.g. 'DRG-DIS')."""
        if edge_label not in EDGE_LABEL_PAIR:
            raise ValueError(f"Unknown edge label {edge_label}")
        src_label, tgt_label = EDGE_LABEL_PAIR[edge_label]

        logger.info(f"Loading {parquet_path.name} ({edge_label}, :{src_label} -> :{tgt_label})")
        df = pl.read_parquet(parquet_path)
        total = df.height
        logger.info(f"  {total:,} rows total")

        # Group by sub-relation and import each into its own Neo4j relationship type
        per_relation_counts: dict[str, int] = {}

        for relation in df["relation"].unique().to_list():
            rel_key = (edge_label, relation)
            neo_rel = EDGE_RELATION_MAP.get(rel_key)
            if neo_rel is None:
                logger.info(f"  skipping {edge_label} {relation} (not in mapping)")
                continue
            sub = df.filter(pl.col("relation") == relation)
            n = sub.height
            logger.info(f"  → {n:,} {edge_label} {relation} -> :{neo_rel}")

            rows = sub.to_dicts()
            # Explicit labels on both MATCH clauses so Neo4j uses the
            # (:Label, id) indexes instead of a full database scan.
            query = f"""
            UNWIND $rows AS row
            MATCH (a:{src_label} {{id: row.from}})
            MATCH (b:{tgt_label} {{id: row.to}})
            MERGE (a)-[r:{neo_rel}]->(b)
            SET r += row.props
            """
            imported = 0
            with self.driver.session() as session:
                for i in range(0, n, self.chunk_size):
                    chunk = rows[i : i + self.chunk_size]
                    payload = []
                    for r in chunk:
                        payload.append({
                            "from": r["from"],
                            "to": r["to"],
                            "props": extract_edge_props(
                                r.get("properties") or {},
                                (r.get("properties") or {}).get("sources"),
                            ),
                        })
                    session.run(query, rows=payload)
                    imported += len(payload)
                    if imported % 100000 == 0 or imported == n:
                        logger.info(f"      ... {imported:,}/{n:,}")
            per_relation_counts[neo_rel] = per_relation_counts.get(neo_rel, 0) + imported

        return per_relation_counts

    # ----- final report -----

    def report(self) -> None:
        logger.info("Final database stats")
        with self.driver.session() as session:
            for label in NODE_LABEL_MAP.values():
                rec = session.run(
                    f"MATCH (n:{label}) RETURN count(n) AS c"
                ).single()
                logger.info(f"  :{label:<10} {rec['c']:,}")
            logger.info("---")
            for rel in [
                "TREATS", "CONTRAINDICATED_FOR", "OFF_LABEL_FOR",
                "CAUSES_SIDE_EFFECT", "ASSOCIATED_WITH",
                "INTERACTS_WITH", "HAS_SYMPTOM",
            ]:
                rec = session.run(
                    f"MATCH ()-[r:{rel}]->() RETURN count(r) AS c"
                ).single()
                logger.info(f"  :{rel:<22} {rec['c']:,}")

            # Sample sanity: Tylenol via trade_names
            logger.info("---")
            logger.info("Sanity check: Tylenol → acetaminophen via trade_names list")
            rec = session.run(
                """
                MATCH (d:Drug)
                WHERE ANY(t IN d.trade_names WHERE toLower(t) = 'tylenol')
                RETURN d.id AS id, d.name AS name, d.trade_names[0..5] AS trade_names
                LIMIT 1
                """
            ).single()
            if rec:
                logger.info(f"  ✓ {rec['id']} ({rec['name']}) — trade_names {rec['trade_names']}")
            else:
                logger.info("  (no Tylenol match found — trade_names lookup may need a different cypher)")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> None:
    p = argparse.ArgumentParser(description="Import OptimusKG slice into Neo4j")
    p.add_argument("--data-dir", type=Path, default=Path("data/optimuskg"))
    p.add_argument("--neo4j-uri", required=True)
    p.add_argument("--neo4j-user", default="neo4j")
    p.add_argument("--neo4j-password", required=True)
    p.add_argument("--clear-db", action="store_true",
                   help="Wipe the database before importing")
    p.add_argument("--skip-nodes", action="store_true",
                   help="Skip node import (assume already loaded)")
    p.add_argument("--skip-edges", action="store_true",
                   help="Skip edge import")
    p.add_argument("--chunk-size", type=int, default=5000)
    args = p.parse_args()

    started = time.time()
    importer = OptimusKGImporter(
        args.neo4j_uri, args.neo4j_user, args.neo4j_password,
        chunk_size=args.chunk_size,
    )

    try:
        if args.clear_db:
            importer.clear_database()
        importer.create_indexes()

        if not args.skip_nodes:
            for fn, optimus_label in [
                ("nodes/drug.parquet", "DRG"),
                ("nodes/disease.parquet", "DIS"),
                ("nodes/phenotype.parquet", "PHE"),
            ]:
                path = args.data_dir / fn
                if not path.exists():
                    logger.warning(f"  missing: {path}; skipping")
                    continue
                importer.import_nodes(path, optimus_label)

        if not args.skip_edges:
            for fn, edge_label in [
                ("edges/drug_disease.parquet", "DRG-DIS"),
                ("edges/drug_phenotype.parquet", "DRG-PHE"),
                ("edges/drug_drug.parquet", "DRG-DRG"),
                ("edges/disease_phenotype.parquet", "DIS-PHE"),
            ]:
                path = args.data_dir / fn
                if not path.exists():
                    logger.warning(f"  missing: {path}; skipping")
                    continue
                importer.import_edges(path, edge_label)

        importer.report()
        logger.info(f"Total time: {time.time() - started:.1f}s")

    finally:
        importer.close()


if __name__ == "__main__":
    main()
