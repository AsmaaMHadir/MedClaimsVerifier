#!/usr/bin/env bash
#
# `make demo` — bring up the Docker compose stack, wait for the API to be
# healthy, then print a quick smoke-test curl.
#
# Requires: docker + docker-compose (or `docker compose` plugin).

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

say()  { printf '\n\033[1;36m▸\033[0m %s\n' "$*"; }
ok()   { printf '  \033[1;32m✓\033[0m %s\n' "$*"; }
die()  { printf '\n\033[1;31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null 2>&1 || die "docker not installed. https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "'docker compose' plugin not available."

[ -f docker/neo4j-seed/load_demo_subset.cypher ] \
  || die "docker/neo4j-seed/load_demo_subset.cypher missing. Run: python scripts/build_demo_subset.py"

say "Building images and starting services …"
docker compose -f docker/docker-compose.yml up -d --build

say "Waiting for API to be healthy (up to 3 min on first run, GLiNER cold-load)…"
for i in {1..90}; do
  if curl -sf http://localhost:8000/health -m 3 >/dev/null 2>&1; then
    ok "API is up"
    break
  fi
  sleep 2
  if [ "$i" -eq 90 ]; then
    die "API didn't come up. Check: docker compose -f docker/docker-compose.yml logs api"
  fi
done

say "Smoke test"
RESULT=$(curl -s -X POST http://localhost:8000/verify \
  -H 'Content-Type: application/json' \
  -d '{"text": "Metformin treats Type 2 Diabetes"}')
STATUS=$(printf '%s' "$RESULT" | python -c "import json,sys; d=json.load(sys.stdin); print(d['claims'][0]['status'] if d.get('claims') else 'NO_CLAIMS')")

if [ "$STATUS" = "SUPPORTED" ]; then
  ok "Verifier returned SUPPORTED for the canonical example."
else
  printf '  \033[1;33m!\033[0m Verifier returned status=%s (expected SUPPORTED). Demo subset may be incomplete.\n' "$STATUS"
fi

cat <<EOF

\033[1;32m✅  MedVerify demo ready.\033[0m
   API:          http://localhost:8000
   Docs:         http://localhost:8000/docs
   Neo4j Browser: http://localhost:7474   (user: neo4j  pass: medverifydemo)

Try a few examples:
   curl -X POST localhost:8000/verify -H 'Content-Type: application/json' \\
     -d '{"text":"Heart attack treated with aspirin"}'

Tear down:
   make demo-down

EOF
