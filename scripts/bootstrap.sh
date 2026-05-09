#!/usr/bin/env bash
#
# MedVerify one-shot setup: runs the four cold-start steps in order, skipping
# any that already completed. Re-run safely after edits to .env or partial
# failures.
#
# Steps:
#   1. Create venv + install requirements
#   2. Copy .env.example -> .env if missing (and stop so user can edit)
#   3. Download OptimusKG parquet files (~400 MB) -> data/optimuskg/
#   4. Import OptimusKG edges into Neo4j (~15-60 min on Aura free)
#   5. Build SapBERT lay-term index (~20 min CPU) -> data/sapbert/

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

# ---------- helpers ----------
say()  { printf '\n\033[1;36m▸\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
warn() { printf '  \033[1;33m!\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

# ---------- 1. venv ----------
say "Step 1/5: Python venv + dependencies"
if [ ! -d venv ] && [ ! -d mcenv ]; then
  python3 -m venv venv
  ok "Created venv/"
fi
# Use whichever venv exists (mcenv first for the project's existing convention)
if [ -d mcenv ]; then VENV=mcenv; else VENV=venv; fi
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --quiet --upgrade pip
pip install --quiet -r requirements.txt
ok "Dependencies installed into $VENV/"

# ---------- 2. .env ----------
say "Step 2/5: Environment file"
if [ ! -f .env ]; then
  cp .env.example .env
  warn "Created .env from template. Open it, fill in NEO4J_URI / NEO4J_PASSWORD, then re-run: make setup"
  exit 0
fi
# Load .env so the next steps see NEO4J_*
set -a
# shellcheck disable=SC1091
source .env
set +a
[ -n "${NEO4J_URI:-}" ] || die ".env missing NEO4J_URI"
[ -n "${NEO4J_PASSWORD:-}" ] || die ".env missing NEO4J_PASSWORD"
ok ".env loaded (Neo4j: ${NEO4J_URI%%/*}//…)"

# ---------- 3. OptimusKG parquet ----------
say "Step 3/5: Download OptimusKG (~400 MB)"
if [ -d data/optimuskg/edges ] && [ "$(ls -A data/optimuskg/edges 2>/dev/null | wc -l)" -gt 0 ]; then
  ok "data/optimuskg/ already populated, skipping download"
else
  python tools/download_optimuskg.py --no-inspect
  ok "OptimusKG parquet files in data/optimuskg/"
fi

# ---------- 4. Load Neo4j ----------
say "Step 4/5: Import KG into Neo4j (~15-60 min depending on tier)"
if [ -f data/.kg_loaded ]; then
  ok "Neo4j already loaded (delete data/.kg_loaded to force re-import)"
else
  python import_optimuskg_to_neo4j.py \
    --neo4j-uri "$NEO4J_URI" \
    --neo4j-user "${NEO4J_USER:-neo4j}" \
    --neo4j-password "$NEO4J_PASSWORD" \
    --data-dir data/optimuskg
  touch data/.kg_loaded
  ok "Neo4j loaded with ~1.58M edges"
fi

# ---------- 5. SapBERT index ----------
say "Step 5/5: Build SapBERT lay-term index (~20 min CPU)"
if [ -f data/sapbert/index_disease.npz ] && [ -f data/sapbert/index_effect.npz ]; then
  ok "SapBERT index present, skipping"
else
  python tools/build_sapbert_index.py
  ok "SapBERT indexes in data/sapbert/"
fi

# ---------- done ----------
printf '\n\033[1;32m✅  MedVerify ready.\033[0m\n'
printf '   API:        make serve         → http://localhost:8000\n'
printf '   Showcase UI: make ui            → http://localhost:3000\n'
printf '   Eval suite: make eval\n\n'
