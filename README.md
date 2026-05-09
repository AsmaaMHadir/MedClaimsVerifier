# MedVerify

Medical claim verification API. Given free-text like *"Heart attack treated with aspirin"*, MedVerify extracts the medical entities, infers the asserted relationship, and verifies it against a 1.6M-edge biomedical knowledge graph, returning a verdict (`SUPPORTED`, `CONTRADICTED`, `NOT_FOUND`, `PARTIAL`, `UNKNOWN`) with the supporting evidence rows.

Built end-to-end: FastAPI backend, Neo4j-backed knowledge graph, GLiNER + LLM hybrid for triple extraction, SapBERT for lay-term canonicalisation, and a Next.js + React showcase UI.

**Eval suite: 90.2% system accuracy** across 80 hand-labelled claims (51 non-data-gap; see [`tests/eval/cases.yaml`](tests/eval/cases.yaml)).

---

## Why it matters

Patient-facing chatbots, EHR copilots, and clinical-decision tools routinely make false claims about drugs and diseases, where a single wrong "X treats Y" or missed contraindication is a regulatory and patient-safety incident. MedVerify is a drop-in verification layer that grounds those claims in a curated biomedical knowledge graph in under two seconds per claim, turning hallucinations into auditable verdicts with cited evidence.

---

## Setup

**Run a demo  (no Neo4j account needed):**
```bash
git clone <repo> && cd medclaimsverifier
make demo            # Docker brings up API + seeded Neo4j (5K-edge subset)
```

**Full setup:**
```bash
git clone <repo> && cd medclaimsverifier
cp .env.example .env # then edit Neo4j creds
make setup           # bootstrap.sh runs the 4 sequential steps below
make serve           # FastAPI on http://localhost:8000
```

`make setup` runs:

| Step | Command | Output |
|------|---------|--------|
| Install deps | `pip install -r requirements.txt` | venv populated |
| Download OptimusKG | `python tools/download_optimuskg.py` | `data/optimuskg/*.parquet` (~400 MB) |
| Load Neo4j | `python import_optimuskg_to_neo4j.py …` | ~1.58M edges in your Neo4j |
| Build SapBERT index | `python tools/build_sapbert_index.py` |`data/sapbert/index_*.npz` (~140 MB) |



Or use it as a Python library:
```python
from medverify_core import MedVerifier
async with MedVerifier(neo4j_uri="…", neo4j_password="…") as v:
    results = await v.verify_text("Heart attack treated with aspirin")
```

---

## How it works

```
                                                   ┌──────────────────────┐
   text ──► GLiNER (biomed)  ──► entities ──►   triple extractor   ──► (subj, predicate, obj, asserted)
                                                ├─ regex rules         │
                                                └─ LLM fallback        │
                                                  (Claude via Bedrock) │
                                                                       ▼
                                                           ┌────────────────────────┐
                                                           │  Knowledge-graph probe │
                                                           │  (Cypher on OptimusKG) │
                                                           └────────────────────────┘
                                                                       │
                                                                  miss?│
                                                                       ▼
                                                          ┌─────────────────────────┐
                                                          │  SapBERT canonicalise   │  e.g.  "heart attack" → "myocardial infarction"
                                                          └─────────────────────────┘
                                                                       │
                                                                       ▼
                                                                   verdict + evidence
```

### 1. Entity extraction: [GLiNER](https://github.com/urchade/GLiNER)
Zero-shot span-scoring NER. Default biomedical variant: `Ihor/gliner-biomed-bi-large-v1.0`. 

### 2. Triple extraction: rules + LLM
A deterministic regex+NegEx layer reads the verb/intent phrase between each entity pair to produce a `(subject, predicate, object, asserted)` triple. Predicates: `TREATS`, `CONTRAINDICATED_FOR`, `CAUSES_SIDE_EFFECT`, `INTERACTS_WITH`, `HAS_SYMPTOM`. When rules return `NONE`, an LLM fallback (Claude via AWS Bedrock or the Anthropic API) resolves the predicate, with a result cache.

### 3. Knowledge graph: [OptimusKG](https://zitnik.hms.harvard.edu) on Neo4j
The successor to PrimeKG by the Zitnik Lab @ Harvard Medical School. ~190K nodes, 21.8M edges, of which we selectively imported ~1.58M edges relevant to claim verification (TREATS, CONTRAINDICATED_FOR, CAUSES_SIDE_EFFECT, INTERACTS_WITH, HAS_SYMPTOM). Synonyms and trade names are first-class node properties, so brand names like *Tylenol* resolve to *acetaminophen* without an external alias service. `TREATS` edges are filtered to FDA-approved indications (clinical trial phase ≥ 4 OR no phase metadata).

### 4. Lay-term canonicalisation: SapBERT
[SapBERT](https://github.com/cambridgeltl/sapbert) (`cambridgeltl/SapBERT-from-PubMedBERT-fulltext`) is fired only as a fallback: when the first Cypher pass returns no rows, the user term is embedded and the nearest canonical OptimusKG node is selected by cosine similarity.

### 5. Verifier: direct + opposite probe
For each triple, the verifier probes the asserted relation first. On miss, it probes the relevant *opposite* relation (e.g. `TREATS` ↔ `CONTRAINDICATED_FOR`) so the system can mark a verdict as `CONTRADICTED` when the KG records the inverse of what the user claimed. Negation is handled symmetrically: a denied claim with no KG edge is `SUPPORTED`, not `NOT_FOUND`.

---

## Running the UIs

After `make setup` (or `make demo`), the API is on `http://localhost:8000`.

```bash
make ui                            # Next.js showcase UI on :3000
streamlit run ui/app.py            # simpler Streamlit fallback on :8501
```

The Next.js UI exercises every API capability: claim verification with highlighted entities, GLiNER playground, KG free-text search, drug/disease profiles, and click-to-expand neighbourhood graphs.

---

## API

| Method | Endpoint                                | Description                                                              |
|--------|-----------------------------------------|--------------------------------------------------------------------------|
| `POST` | `/verify`                               | Verify medical claims in text                                            |
| `POST` | `/extract`                              | Extract medical entities from text (GLiNER playground)                   |
| `GET`  | `/drug/{name}`                          | Drug profile (indications, side effects, contraindications, interactions)|
| `GET`  | `/disease/{name}`                       | Disease profile (treatments, symptoms, related conditions)               |
| `GET`  | `/search?q=`                            | Free-text knowledge graph search                                         |
| `GET`  | `/neighborhood/{type}/{name}?limit=`    | One-hop neighbourhood (used by the Next.js graph explorer)               |
| `GET`  | `/health`                               | Service health (Neo4j, GLiNER, model versions)                           |

---

## Using the API

All endpoints return JSON. Add `-H 'X-API-Key: <key>'` only if you set `API_KEYS` in your `.env`. Interactive Swagger docs are available at `http://localhost:8000/docs`.

### Verify a claim: `POST /verify`

```bash
curl -s -X POST http://localhost:8000/verify \
  -H 'Content-Type: application/json' \
  -d '{"text": "Heart attack treated with aspirin"}' | jq
```

```json
{
  "success": true,
  "processing_time_ms": 1247.83,
  "claims": [{
    "claim": "aspirin treats Heart attack",
    "status": "SUPPORTED",
    "confidence": 0.81,
    "asserted_predicate": "TREATS",
    "evidence_predicate": "TREATS",
    "negated": false,
    "entities": [
      {"text": "aspirin",      "type": "Drug",    "start": 25, "end": 32, "confidence": 0.93},
      {"text": "Heart attack", "type": "Disease", "start":  0, "end": 12, "confidence": 0.91}
    ],
    "evidence": [
      {"source": "OptimusKG", "relationship": "TREATS",
       "subject": "ASPIRIN", "object": "myocardial infarction"},
      {"source": "OptimusKG", "relationship": "TREATS",
       "subject": "ASPIRIN", "object": "acute myocardial infarction"}
    ]
  }]
}
```

**Body fields**

| Field | Type | Required | Notes |
|---|---|---|---|
| `text` | string | yes | 1–50,000 chars. Multiple sentences produce multiple claims. |

**Status values:** `SUPPORTED`, `CONTRADICTED`, `NOT_FOUND`, `PARTIAL`, `UNKNOWN`. See [`tests/eval/cases.yaml`](tests/eval/cases.yaml) for examples of each.

### Extract entities: `POST /extract`

```bash
curl -s -X POST http://localhost:8000/extract \
  -H 'Content-Type: application/json' \
  -d '{"text": "Patient takes Metformin for Type 2 Diabetes and reports muscle pain."}' | jq
```

Returns the same `Entity` shape as `/verify` without running the verifier; useful for previewing what GLiNER sees.

### Drug profile: `GET /drug/{name}`

```bash
curl -s http://localhost:8000/drug/metformin | jq
```

```json
{
  "drug":              "METFORMIN",
  "indications":       ["type 2 diabetes mellitus", "polycystic ovary syndrome", ...],
  "contraindications": ["lactic acidosis", "kidney disease", ...],
  "side_effects":      ["Diarrhoea", "Nausea", "Vitamin B12 deficiency", ...],
  "interactions":      ["INSULIN", "GLIPIZIDE", ...]
}
```

Brand names work: `/drug/tylenol` resolves through OptimusKG's `trade_names` array to acetaminophen.

### Disease profile: `GET /disease/{name}`

```bash
curl -s http://localhost:8000/disease/diabetes | jq
```

Returns `treatments`, `symptoms`, and `related_conditions` arrays.

### Free-text KG search: `GET /search?q=`

```bash
curl -s 'http://localhost:8000/search?q=diabet' | jq
```

Substring match across drug, disease, and effect names. Returns up to 10 results with `name`, `id`, and `labels`.

### Graph neighbourhood: `GET /neighborhood/{type}/{name}`

```bash
curl -s 'http://localhost:8000/neighborhood/Drug/metformin?limit=10' | jq
```

| Path/query param | Notes |
|---|---|
| `{type}` | `Drug` or `Disease` (others return `400 INVALID_TYPE`) |
| `{name}` | min 2 chars (else `400 INVALID_NAME`) |
| `?limit=` | 1–25, capped server-side |

Returns `{nodes: [...], edges: [...]}` shaped for the Next.js force-graph component.

### Health: `GET /health`

```bash
curl -s http://localhost:8000/health | jq
```

Reports Neo4j and GLiNER status with per-service latency.

### Errors

| Code | When |
|---|---|
| `400` | invalid path params on `/neighborhood` |
| `401` | `X-API-Key` missing or wrong (only when `API_KEYS` is set) |
| `422` | request body fails Pydantic validation (e.g. `text` empty or > 50K chars) |
| `429` | rate-limited (default 60 req/min/IP) |
| `503` | downstream Neo4j or GLiNER failure |

### Python: using `medverify_core` directly

For in-process integration (e.g. inside a RAG pipeline) skip the HTTP layer and call the library:

```python
import asyncio
from medverify_core import MedVerifier, VerificationStatus

async def main():
    async with MedVerifier(
        neo4j_uri="neo4j+s://your-instance.databases.neo4j.io",
        neo4j_password="your-password",
        enable_llm_fallback=False,   # opt out of Anthropic/Bedrock
    ) as v:
        results = await v.verify_text("Heart attack treated with aspirin")
        for r in results:
            print(r.status, "-", r.claim)
            if r.status == VerificationStatus.SUPPORTED:
                for e in r.evidence[:2]:
                    print(f"  evidence: {e.subject} -[{e.relationship}]-> {e.object}")

asyncio.run(main())
```

Other library methods: `extract_entities(text)`, `get_drug_info(name)`, `get_disease_info(name)`. Configuration is fully overridable via constructor kwargs or `MedVerifierConfig.from_env()`.

---

## Evaluation

```bash
python tools/eval.py                  # full suite
python tools/eval.py --tag negation   # filter by tag
```


| Metric                   | Value           |
|--------------------------|-----------------|
| System accuracy          | **90.2% (46/51)** |
| Predicate extraction     | 97.1% (68/70)   |
| Negation detection       | 100% (76/76)    |
| Latency p50 / p95        | 1.07s / 2.25s   |

The `data_gap` tag flags cases failing because the KG lacks the edge

---

## Project structure

```
medclaimsverifier/
├── medverify_core/                      # Importable Python library
│   ├── verifier.py                      # MedVerifier facade (async-context-manager)
│   └── config.py                        # MedVerifierConfig dataclass
├── src/                                 # FastAPI service
│   ├── main.py                          # app & lifespan
│   ├── api/routes.py                    # API endpoints
│   ├── config/                          # settings, structured logging
│   ├── middleware/auth.py               # API-key auth
│   ├── models/                          # request/response schemas (Pydantic v2)
│   └── services/
│       ├── gliner_client.py             # GLiNER entity extraction
│       ├── claim_triple_extractor.py    # rules + LLM triple extraction
│       ├── llm_predicate_resolver.py    # Bedrock/Anthropic predicate fallback
│       ├── predicates.py                # regex predicate library
│       ├── knowledge_graph.py           # async Neo4j queries + SapBERT fallback
│       ├── sapbert_normalizer.py        # lay-term → canonical resolver
│       ├── drug_normalizer.py           # RxNorm cascade for brand drugs
│       ├── claim_verifier.py            # verdict assembly + opposite-probe logic
│       ├── verification_logger.py       # per-call structured trace
│       └── cache.py                     # TTL response cache
├── tools/                               # one-shot CLIs (download, build, eval)
├── tests/                               # unit + 80-case eval suite
├── ui-web/                              # Next.js + React showcase UI
├── ui/app.py                            # Streamlit fallback UI
├── docker/                              # docker-compose demo + seeded Neo4j
├── scripts/bootstrap.sh                 # the make-setup workhorse
├── Makefile                             # setup / serve / ui / eval / test / demo
├── pyproject.toml                       # medverify-core packaging
├── import_optimuskg_to_neo4j.py         # one-time KG import
├── requirements.txt
└── .env.example
```

---

## Configuration

| Variable                    | Description                                       | Default                              |
|-----------------------------|---------------------------------------------------|--------------------------------------|
| `NEO4J_URI`                 | Neo4j connection URI                              | _(required)_                         |
| `NEO4J_USER`                | Neo4j username                                    | `neo4j`                              |
| `NEO4J_PASSWORD`            | Neo4j password                                    | _(required)_                         |
| `GLINER_MODEL`              | GLiNER model id                                   | `Ihor/gliner-biomed-bi-large-v1.0`   |
| `GLINER_THRESHOLD`          | Span confidence floor                             | `0.5`                                |
| `ANTHROPIC_API_KEY`         | Direct Anthropic API key for predicate fallback   | _(empty → fallback disabled)_        |
| `AWS_BEARER_TOKEN_BEDROCK`  | AWS Bedrock token (alternative to Anthropic)      | _(empty)_                            |
| `BEDROCK_MODEL`             | Bedrock model id                                  | _(empty → fallback disabled)_        |
| `LLM_FALLBACK_ENABLED`      | Toggle LLM predicate fallback                     | `true`                               |
| `API_KEYS`                  | JSON list of allowed keys (empty list = public)   | `[]`                                 |
| `RATE_LIMIT_PER_MINUTE`     | Per-client rate limit                             | `60`                                 |
| `CORS_ORIGINS`              | JSON list of allowed origins                      | `["http://localhost:3000","http://localhost:8501"]` |

---

## Tech stack

FastAPI · Pydantic v2 · Neo4j (async) · GLiNER · SapBERT (PubMedBERT) · Anthropic Claude (Bedrock-compatible) · loguru · slowapi · Next.js 14 + React + Tailwind · Streamlit

---

## Testing

```bash
pytest tests/ -v          # unit + integration suite
python tools/eval.py      # claim-verification eval (90.2% system accuracy)
```
