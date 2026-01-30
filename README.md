# MedVerify API

Medical claim verification API that extracts drug, disease, and symptom entities from text and verifies their relationships against the PrimeKG knowledge graph.

## Architecture

```
User Input (text) ──> GLiNER (entity extraction) ──> Neo4j / PrimeKG (verification)
                          │                                    │
                     Drugs, Diseases,                   TREATS, CONTRAINDICATED,
                     Symptoms                           SIDE_EFFECT, INTERACTS
                          │                                    │
                          └──────────── Verified Claims ───────┘
```

**Entity Extraction** — [GLiNER](https://github.com/urchade/GLiNER) (zero-shot NER) extracts medical entities with specific types (Drug, Disease, Symptom) directly from text. Runs locally, no external API needed.

**Knowledge Graph** — [PrimeKG](https://github.com/mims-harvard/PrimeKG) loaded into Neo4j Aura. Contains 44,316 nodes and 2.4M+ relationships covering drug-disease, drug-side-effect, disease-symptom, and drug-drug interaction data.

## Quick Start

```bash
# 1. Create virtual environment
python -m venv venv
source venv/bin/activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Copy environment template and fill in your Neo4j credentials
cp .env.example .env

# 4. Run the API
uvicorn src.main:app --reload
```

The GLiNER model (~500MB) downloads automatically on first request.

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/verify` | Verify medical claims in text |
| `POST` | `/extract` | Extract medical entities from text |
| `GET` | `/drug/{name}` | Get drug info (indications, side effects, interactions) |
| `GET` | `/disease/{name}` | Get disease info (treatments, symptoms) |
| `GET` | `/search?q=` | Search the knowledge graph |
| `GET` | `/health` | Service health check |

### Example: Verify a Claim

```bash
curl -X POST http://localhost:8000/verify \
  -H "Content-Type: application/json" \
  -d '{"text": "Metformin is used to treat Type 2 Diabetes"}'
```

### Example: Extract Entities

```bash
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient presents with hypertension and was prescribed lisinopril"}'
```

## Project Structure

```
medclaimsverifier/
├── src/
│   ├── main.py                  # FastAPI app entry point
│   ├── api/
│   │   └── routes.py            # API endpoints
│   ├── config/
│   │   ├── settings.py          # Environment configuration
│   │   └── logging.py           # Structured logging (loguru)
│   ├── middleware/
│   │   └── auth.py              # API key authentication
│   ├── models/
│   │   ├── requests.py          # Request models
│   │   └── responses.py         # Response models
│   └── services/
│       ├── gliner_client.py     # GLiNER entity extraction
│       ├── knowledge_graph.py   # Neo4j async queries
│       ├── claim_verifier.py    # Verification logic
│       └── cache.py             # Response caching
├── tests/
│   ├── conftest.py              # Shared test fixtures
│   ├── test_api.py              # API endpoint tests
│   ├── test_claim_verifier.py   # Verifier unit tests
│   └── test_knowledge_graph.py  # Knowledge graph tests
├── ui/
│   └── app.py                   # Streamlit UI
├── requirements.txt
├── .env.example
└── README.md
```

## Configuration

All configuration is via environment variables (see `.env.example`):

| Variable | Description | Default |
|----------|-------------|---------|
| `NEO4J_URI` | Neo4j connection URI | — |
| `NEO4J_USER` | Neo4j username | `neo4j` |
| `NEO4J_PASSWORD` | Neo4j password | — |
| `API_HOST` | API bind host | `0.0.0.0` |
| `API_PORT` | API bind port | `8000` |
| `LOG_LEVEL` | Logging level | `INFO` |
| `RATE_LIMIT_PER_MINUTE` | Rate limit per client | `60` |
| `API_KEYS` | Comma-separated API keys (empty = public) | — |
| `CORS_ORIGINS` | Allowed CORS origins | `localhost:8501,localhost:3000` |

## Production Features

- **Rate Limiting** — slowapi with configurable per-minute limits
- **API Key Auth** — Optional `X-API-Key` header authentication
- **CORS** — Configurable allowed origins
- **Response Caching** — TTL-based caching for knowledge graph lookups
- **Structured Logging** — loguru with file rotation and error separation
- **Async Neo4j** — Non-blocking database queries

## Running Tests

```bash
pytest tests/ -v
```

## Tech Stack

- **FastAPI** — Async Python web framework
- **GLiNER** — Zero-shot named entity recognition
- **Neo4j** — Graph database (async driver)
- **PrimeKG** — Biomedical knowledge graph
- **Pydantic v2** — Data validation
- **loguru** — Structured logging
- **slowapi** — Rate limiting
