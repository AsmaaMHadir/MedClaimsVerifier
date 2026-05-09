# MedVerify developer entrypoints.
# Run `make help` for the full list. All targets are idempotent and re-runnable.

VENV ?= mcenv
PY    = $(VENV)/bin/python
PIP   = $(VENV)/bin/pip

.PHONY: help setup serve ui eval test demo demo-down clean

help:
	@printf 'MedVerify — common targets\n'
	@printf '  make setup       Bootstrap (deps + KG + SapBERT). Re-runnable.\n'
	@printf '  make serve       Run the FastAPI service on :8000\n'
	@printf '  make ui          Run the Next.js showcase UI on :3000\n'
	@printf '  make eval        Run the 80-case evaluation suite\n'
	@printf '  make test        Run unit + integration tests\n'
	@printf '  make demo        Bring up Docker demo (API + seeded Neo4j)\n'
	@printf '  make demo-down   Tear down the Docker demo\n'
	@printf '  make clean       Remove caches, generated indexes, results\n'

setup:
	bash scripts/bootstrap.sh

serve:
	$(VENV)/bin/uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

ui:
	cd ui-web && npm install && npm run dev

eval:
	$(PY) tools/eval.py

test:
	$(VENV)/bin/pytest tests/ -v --ignore=tests/quality_eval.py

demo:
	bash scripts/demo.sh

demo-down:
	docker compose -f docker/docker-compose.yml down

clean:
	rm -rf .pytest_cache __pycache__ src/**/__pycache__ tests/**/__pycache__
	rm -rf tests/eval/results/*.csv tests/eval/audit_report.md
	rm -f tools/coverage_report.json tools/lay_term_coverage.csv tools/verification_log.csv
