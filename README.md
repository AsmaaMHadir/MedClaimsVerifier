# MedVerify

Medical claim verification API. Given free-text like *"Heart attack treated with aspirin"*, MedVerify extracts the medical entities, infers the asserted relationship, and verifies it against a 1.6M-edge biomedical knowledge graph, returning a verdict (`SUPPORTED`, `CONTRADICTED`, `NOT_FOUND`, `PARTIAL`, `UNKNOWN`) with the supporting evidence rows.

Built end-to-end: FastAPI backend, Neo4j-backed knowledge graph, GLiNER + LLM hybrid for triple extraction, SapBERT for lay-term canonicalisation, and a Next.js + React showcase UI.

**Eval suite: 90.2% system accuracy** across 80 hand-labelled claims (51 non-data-gap; see [`tests/eval/cases.yaml`](tests/eval/cases.yaml)).

---

## Why it matters

Patient-facing chatbots, EHR copilots, and clinical-decision tools routinely make false claims about drugs and diseases, where a single wrong "X treats Y" or missed contraindication is a regulatory and patient-safety incident. MedVerify is a drop-in verification layer that grounds those claims in a curated biomedical knowledge graph in under two seconds per claim, turning hallucinations into auditable verdicts with cited evidence.

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
Zero-shot span-scoring NER. Default biomedical variant: `Ihor/gliner-biomed-bi-large-v1.0`. Runs locally; no external API needed.

### 2. Triple extraction: rules + LLM
A deterministic regex+NegEx layer reads the verb/intent phrase between each entity pair to produce a `(subject, predicate, object, asserted)` triple. Predicates: `TREATS`, `CONTRAINDICATED_FOR`, `CAUSES_SIDE_EFFECT`, `INTERACTS_WITH`, `HAS_SYMPTOM`. When rules return `NONE`, an LLM fallback (Claude via AWS Bedrock or the Anthropic API) resolves the predicate, with a result cache so production traffic doesn't re-pay.

### 3. Knowledge graph: [OptimusKG](https://zitnik.hms.harvard.edu) on Neo4j
The successor to PrimeKG by the Zitnik Lab @ Harvard Medical School. ~190K nodes, 21.8M edges, of which we selectively imported ~1.58M edges relevant to claim verification (TREATS, CONTRAINDICATED_FOR, CAUSES_SIDE_EFFECT, INTERACTS_WITH, HAS_SYMPTOM). Synonyms and trade names are first-class node properties, so brand names like *Tylenol* resolve to *acetaminophen* without an external alias service. `TREATS` edges are filtered to FDA-approved indications (clinical trial phase ≥ 4 OR no phase metadata).

### 4. Lay-term canonicalisation: SapBERT
[SapBERT](https://github.com/cambridgeltl/sapbert) (`cambridgeltl/SapBERT-from-PubMedBERT-fulltext`) is fired only as a fallback: when the first Cypher pass returns no rows, the user term is embedded and the nearest canonical OptimusKG node is selected by cosine similarity (threshold 0.77). Recovers cases like *heart attack* → *myocardial infarction*, *high blood pressure* → *hypertension*, *allergies* → *allergic disease*. Indexes (~138 MB) are pre-built once and persisted to disk; per-query lookups are cached in SQLite.

### 5. Verifier: direct + opposite probe
For each triple, the verifier probes the asserted relation first. On miss, it probes the relevant *opposite* relation (e.g. `TREATS` ↔ `CONTRAINDICATED_FOR`) so the system can mark a verdict as `CONTRADICTED` when the KG records the inverse of what the user claimed. Negation is handled symmetrically: a denied claim with no KG edge is `SUPPORTED`, not `NOT_FOUND`.

---

## Quick start

### Backend (FastAPI)

```bash
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# fill in NEO4J_URI / NEO4J_PASSWORD; optionally ANTHROPIC_API_KEY or AWS Bedrock creds

# Build the SapBERT index (one-time, ~20 min on CPU)
python tools/build_sapbert_index.py

uvicorn src.main:app --reload --port 8000
```

GLiNER weights (~1–2 GB) download on first request.

### Showcase UI (Next.js + React)

```bash
cd ui-web
cp .env.local.example .env.local
npm install
npm run dev    # http://localhost:3000
```

A simpler Streamlit UI at [`ui/app.py`](ui/app.py) is also available (`streamlit run ui/app.py`).

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

### Example

```bash
curl -X POST http://localhost:8000/verify \
  -H 'Content-Type: application/json' \
  -d '{"text": "Heart attack treated with aspirin"}'
```

```json
{
  "claims": [{
    "claim": "aspirin treats Heart attack",
    "status": "SUPPORTED",
    "confidence": 0.81,
    "evidence": [
      {"source": "OptimusKG", "relationship": "TREATS",
       "subject": "ASPIRIN", "object": "myocardial infarction"},
      {"source": "OptimusKG", "relationship": "TREATS",
       "subject": "ASPIRIN", "object": "acute myocardial infarction"}
    ]
  }]
}
```

---

## Evaluation

```bash
python tools/eval.py                  # full suite (~110s)
python tools/eval.py --tag negation   # filter by tag
```

Reports raw + system accuracy, per-verdict precision/recall, confusion matrix, predicate-extraction and negation accuracy, latency p50/p95/max, and a CSV of per-case results under `tests/eval/results/`.

| Metric                   | Value           |
|--------------------------|-----------------|
| System accuracy          | **90.2% (46/51)** |
| Predicate extraction     | 97.1% (68/70)   |
| Negation detection       | 100% (76/76)    |
| Latency p50 / p95        | 1.07s / 2.25s   |

The `data_gap` tag flags cases failing because the KG genuinely lacks the edge. They are excluded from system accuracy but reported separately so you can see the headroom.

---

## Project structure

```
medclaimsverifier/
├── src/
│   ├── main.py                          # FastAPI app & lifespan
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
├── tools/
│   ├── build_sapbert_index.py           # one-time embedding builder
│   ├── eval.py                          # in-process evaluation harness
│   ├── audit_eval_labels.py             # validate eval labels vs current KG
│   └── scan_kg_coverage.py              # KG coverage diagnostics
├── tests/
│   ├── eval/cases.yaml                  # 80 hand-labelled cases
│   ├── test_claim_verifier.py
│   ├── test_knowledge_graph.py
│   └── test_api.py
├── ui-web/                              # Next.js + React showcase UI
├── ui/app.py                            # Streamlit fallback UI
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
| `GLINER_MODEL`              | GLiNER model id                                   | `urchade/gliner_medium-v2.1`         |
| `GLINER_THRESHOLD`          | Span confidence floor                             | `0.5`                                |
| `ANTHROPIC_API_KEY`         | Direct Anthropic API key for predicate fallback   | _(empty → fallback disabled)_        |
| `AWS_BEARER_TOKEN_BEDROCK`  | AWS Bedrock token (alternative to Anthropic)      | _(empty)_                            |
| `BEDROCK_MODEL`             | Bedrock model id                                  | `claude-haiku-4-5`                   |
| `LLM_FALLBACK_ENABLED`      | Toggle LLM predicate fallback                     | `true`                               |
| `API_KEYS`                  | Comma-separated keys (empty = public)             | _(empty)_                            |
| `RATE_LIMIT_PER_MINUTE`     | Per-client rate limit                             | `60`                                 |
| `CORS_ORIGINS`              | Comma-separated allowed origins                   | `http://localhost:8501,http://localhost:3000` |

---

## Production features

- **Rate limiting**: slowapi with per-route override and configurable per-minute limits
- **API-key auth**: optional `X-API-Key` header (skipped when `API_KEYS` is empty)
- **CORS**: configurable allowed origins
- **Response caching**: TTL-keyed cache for KG lookups and SapBERT mappings
- **Structured logging**: loguru with file rotation + error separation
- **Async Neo4j**: non-blocking driver, connection reuse via lifespan
- **Graceful degradation**: LLM fallback, SapBERT, RxNorm cascade are all optional; the verifier degrades cleanly when keys/indexes are missing

---

## Tech stack

FastAPI · Pydantic v2 · Neo4j (async) · GLiNER · SapBERT (PubMedBERT) · Anthropic Claude (Bedrock-compatible) · loguru · slowapi · Next.js 14 + React + Tailwind · Streamlit

---

## Testing

```bash
pytest tests/ -v          # unit + integration suite
python tools/eval.py      # claim-verification eval (90.2% system accuracy)
```
