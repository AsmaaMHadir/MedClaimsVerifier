# MedVerify API - Technical Documentation

## Complete Developer Guide for Medical Claim Verification System

---

# Table of Contents

1. [Product Overview](#1-product-overview)
2. [System Architecture](#2-system-architecture)
3. [Current Implementation Status](#3-current-implementation-status)
4. [Component Details](#4-component-details)
5. [API Specifications](#5-api-specifications)
6. [Database Schema](#6-database-schema)
7. [Development Setup](#7-development-setup)
8. [Deployment Guide](#8-deployment-guide)
9. [Development Roadmap](#9-development-roadmap)
10. [Testing Guide](#10-testing-guide)
11. [Appendix](#11-appendix)

---

# 1. Product Overview

## 1.1 What is MedVerify?

MedVerify is a **Medical Claim Verification API** that validates medical statements against a knowledge graph of verified medical relationships. It addresses the critical problem of **AI hallucinations in healthcare** — where AI systems generate plausible but incorrect medical information.

### The Problem We Solve

- AI-generated medical content has **17-34% error rates** in healthcare applications
- Existing fact-checking tools don't understand medical terminology or relationships
- Manual verification by medical professionals doesn't scale

### Our Solution

An API that:
1. Extracts medical entities (drugs, diseases, symptoms) from text
2. Verifies relationships against a curated medical knowledge graph
3. Returns structured verification results with evidence

## 1.2 Example Use Case

**Input:**
```json
{
  "text": "Metformin is commonly prescribed to treat Type 2 Diabetes and may cause gastrointestinal side effects."
}
```

**Output:**
```json
{
  "success": true,
  "claims": [
    {
      "claim": "Metformin treats Type 2 Diabetes",
      "status": "SUPPORTED",
      "confidence": 0.95,
      "evidence": ["PrimeKG: Metformin TREATS Diabetes Mellitus, Type 2"]
    },
    {
      "claim": "Metformin causes gastrointestinal side effects",
      "status": "SUPPORTED", 
      "confidence": 0.89,
      "evidence": ["PrimeKG: Metformin CAUSES_SIDE_EFFECT Gastrointestinal disorder"]
    }
  ]
}
```

## 1.3 Target Users

| User Type | Use Case |
|-----------|----------|
| **AI Healthcare Companies** | Verify LLM outputs before showing to patients |
| **Medical Content Platforms** | Fact-check articles and educational content |
| **Clinical Decision Support** | Validate AI-generated treatment suggestions |
| **Pharmaceutical Companies** | Verify drug information in marketing materials |
| **Health Tech Startups** | Add verification layer to chatbots |

## 1.4 Business Model

- **Freemium API**: 1,000 free verifications/month
- **Pro Tier**: $99/month for 50,000 verifications
- **Enterprise**: Custom pricing with SLA guarantees

---

# 2. System Architecture

## 2.1 High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLIENT APPLICATIONS                             │
│                    (Healthcare Apps, Chatbots, Content Platforms)            │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼ HTTPS
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MEDVERIFY API                                   │
│                         (FastAPI - To Be Built)                              │
│  ┌─────────────┐  ┌─────────────────┐  ┌─────────────────────────────────┐  │
│  │   /verify   │  │    /extract     │  │  /drug/{name}  /disease/{name}  │  │
│  └─────────────┘  └─────────────────┘  └─────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────────┘
                          │                              │
                          ▼                              ▼
┌─────────────────────────────────────┐  ┌────────────────────────────────────┐
│         MEDCAT SERVICE              │  │       KNOWLEDGE GRAPH SERVICE       │
│     (Modal - DEPLOYED ✅)           │  │        (Neo4j Aura - DEPLOYED ✅)   │
│                                     │  │                                    │
│  • Entity Extraction (NER)          │  │  • 44,316 medical nodes            │
│  • SNOMED-CT Linking                │  │  • 2,426,257 relationships         │
│  • Negation Detection               │  │  • Drug-Disease-Symptom graph      │
│  • 400K+ medical concepts           │  │  • Cypher query interface          │
│                                     │  │                                    │
│  URL: https://asmaamhadir--medcat   │  │  URI: neo4j+s://84b5974e.databases │
│       -api-fastapi-app.modal.run    │  │       .neo4j.io                    │
└─────────────────────────────────────┘  └────────────────────────────────────┘
```

## 2.2 Data Flow

```
1. Client sends text → MedVerify API
                            │
2. API calls MedCAT ────────┼──→ Extract entities (drugs, diseases, symptoms)
                            │         │
                            │         ▼
                            │    [Drug: Metformin, CUI: C0025598]
                            │    [Disease: Diabetes, CUI: C0011847]
                            │
3. API queries Neo4j ───────┼──→ Check relationships exist
                            │         │
                            │         ▼
                            │    MATCH (d:Drug)-[:TREATS]->(dis:Disease)
                            │    WHERE d.name = 'Metformin' 
                            │      AND dis.name CONTAINS 'Diabetes'
                            │
4. API returns result ──────┼──→ {status: "SUPPORTED", evidence: [...]}
```

## 2.3 Technology Stack

| Layer | Technology | Purpose |
|-------|------------|---------|
| **API Framework** | FastAPI | REST API with async support |
| **NLP/NER** | MedCAT + SNOMED-CT | Medical entity extraction |
| **Knowledge Graph** | Neo4j Aura | Medical relationship storage |
| **Graph Data** | PrimeKG (Harvard) | Pre-built medical relationships |
| **Deployment (NLP)** | Modal | Serverless ML model hosting |
| **Deployment (API)** | TBD (Railway/Render) | Main API hosting |

---

# 3. Current Implementation Status

## 3.1 What's Done ✅

### MedCAT Entity Extraction Service (Modal)
- **Status**: DEPLOYED AND RUNNING
- **URL**: `https://asmaamhadir--medcat-api-fastapi-app.modal.run`
- **Features**:
  - `/extract` endpoint for entity extraction
  - `/health` endpoint for status checks
  - MedCAT v2 SNOMED 2025 model (trained on MIMIC-IV)
  - 400K+ medical concepts
  - Negation detection

### Neo4j Knowledge Graph (Neo4j Aura)
- **Status**: DEPLOYED WITH DATA
- **URI**: `neo4j+s://84b5974e.databases.neo4j.io`
- **Credentials**: 
  - User: `neo4j`
  - Password: `ZnDSrk6RHNG-2ht5S45eg9chOd-anNA0Fbk19_59HQM`
- **Data Loaded**:
  - 44,316 nodes (drugs, diseases, phenotypes, genes)
  - 2,426,257 relationships
  - Source: PrimeKG (Harvard)

### Relationship Types in Neo4j

| Relationship | Count | Description |
|--------------|-------|-------------|
| `TREATS` | ~18,776 | Drug treats disease (indications) |
| `CONTRAINDICATED_FOR` | ~61,350 | Drug should not be used for condition |
| `CAUSES_SIDE_EFFECT` | ~129,568 | Drug causes adverse effect |
| `HAS_SYMPTOM` | ~300,634 | Disease manifests symptom |
| `INTERACTS_WITH` | ~2,672,628 | Drug-drug interactions |

## 3.2 What Needs to Be Built 🔨

### Main MedVerify API
The orchestration layer that connects MedCAT and Neo4j:

```
src/
├── api/
│   ├── __init__.py
│   ├── routes.py           # FastAPI endpoints
│   └── dependencies.py     # Dependency injection
├── services/
│   ├── __init__.py
│   ├── medcat_client.py    # Calls Modal MedCAT API
│   ├── knowledge_graph.py  # Neo4j queries
│   └── claim_verifier.py   # Verification logic
├── models/
│   ├── __init__.py
│   ├── requests.py         # Pydantic request models
│   └── responses.py        # Pydantic response models
├── config/
│   ├── __init__.py
│   └── settings.py         # Environment configuration
└── main.py                 # FastAPI app entry point
```

---

# 4. Component Details

## 4.1 MedCAT Service (Deployed on Modal)

### What It Does
Extracts medical entities from text and links them to SNOMED-CT concepts.

### API Endpoint
```
POST https://asmaamhadir--medcat-api-fastapi-app.modal.run/extract
```

### Request Format
```json
{
  "text": "Patient diagnosed with Type 2 Diabetes and prescribed Metformin 500mg twice daily."
}
```

### Response Format
```json
{
  "entities": [
    {
      "text": "Type 2 Diabetes",
      "cui": "C0011860",
      "name": "Diabetes Mellitus, Type 2",
      "types": ["T047"],
      "confidence": 0.95,
      "start": 24,
      "end": 39,
      "negated": false
    },
    {
      "text": "Metformin",
      "cui": "C0025598",
      "name": "Metformin",
      "types": ["T109", "T121"],
      "confidence": 0.98,
      "start": 55,
      "end": 64,
      "negated": false
    }
  ],
  "count": 2
}
```

### Entity Fields Explained
| Field | Description |
|-------|-------------|
| `text` | Original text span from input |
| `cui` | Concept Unique Identifier (UMLS/SNOMED) |
| `name` | Canonical name of the concept |
| `types` | Semantic type codes (T047=Disease, T109=Drug) |
| `confidence` | Model confidence score (0-1) |
| `start`/`end` | Character offsets in original text |
| `negated` | Whether entity is negated ("no diabetes" → true) |

### Python Client Example
```python
import httpx

MEDCAT_URL = "https://asmaamhadir--medcat-api-fastapi-app.modal.run"

async def extract_entities(text: str) -> dict:
    async with httpx.AsyncClient() as client:
        response = await client.post(
            f"{MEDCAT_URL}/extract",
            json={"text": text},
            timeout=60.0  # First request may be slow (cold start)
        )
        return response.json()
```

## 4.2 Neo4j Knowledge Graph

### Connection Details
```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "neo4j+s://84b5974e.databases.neo4j.io",
    auth=("neo4j", "ZnDSrk6RHNG-2ht5S45eg9chOd-anNA0Fbk19_59HQM")
)
```

### Node Types (Labels)
| Label | Description | Example |
|-------|-------------|---------|
| `Drug` | Pharmaceutical compounds | Metformin, Aspirin |
| `Disease` | Medical conditions | Diabetes, Hypertension |
| `Gene` | Genes/Proteins | BRCA1, Insulin receptor |
| `Phenotype` | Observable traits | Obesity, Fever |
| `Effect` | Side effects | Nausea, Headache |
| `Anatomy` | Body parts | Liver, Heart |

### Relationship Types
| Type | From → To | Description |
|------|-----------|-------------|
| `TREATS` | Drug → Disease | Drug is indicated for disease |
| `CONTRAINDICATED_FOR` | Drug → Disease | Drug should not be used |
| `CAUSES_SIDE_EFFECT` | Drug → Effect | Drug may cause this effect |
| `HAS_SYMPTOM` | Disease → Phenotype | Disease presents with symptom |
| `INTERACTS_WITH` | Drug → Drug | Drug interaction exists |
| `ASSOCIATED_WITH_GENE` | Disease → Gene | Genetic association |
| `TARGETS` | Drug → Gene | Drug targets this gene |

### Essential Cypher Queries

#### Check if Drug Treats Disease
```cypher
MATCH (d:Drug)-[r:TREATS]->(dis:Disease)
WHERE toLower(d.name) CONTAINS toLower($drug_name)
  AND toLower(dis.name) CONTAINS toLower($disease_name)
RETURN d.name as drug, dis.name as disease, type(r) as relationship
LIMIT 5
```

#### Check Contraindications
```cypher
MATCH (d:Drug)-[r:CONTRAINDICATED_FOR]->(dis:Disease)
WHERE toLower(d.name) CONTAINS toLower($drug_name)
  AND toLower(dis.name) CONTAINS toLower($condition_name)
RETURN d.name as drug, dis.name as condition
LIMIT 5
```

#### Get Drug Side Effects
```cypher
MATCH (d:Drug)-[r:CAUSES_SIDE_EFFECT]->(e:Effect)
WHERE toLower(d.name) CONTAINS toLower($drug_name)
RETURN d.name as drug, collect(DISTINCT e.name)[0..10] as side_effects
```

#### Get All Drug Information
```cypher
MATCH (d:Drug)
WHERE toLower(d.name) CONTAINS toLower($drug_name)
WITH d LIMIT 1
OPTIONAL MATCH (d)-[:TREATS]->(dis:Disease)
WITH d, collect(DISTINCT dis.name)[0..5] as treats
OPTIONAL MATCH (d)-[:CONTRAINDICATED_FOR]->(contra:Disease)
WITH d, treats, collect(DISTINCT contra.name)[0..5] as contraindications
OPTIONAL MATCH (d)-[:CAUSES_SIDE_EFFECT]->(eff:Effect)
RETURN d.name as drug, treats, contraindications, 
       collect(DISTINCT eff.name)[0..5] as side_effects
```

#### Get Disease Information
```cypher
MATCH (dis:Disease)
WHERE toLower(dis.name) CONTAINS toLower($disease_name)
WITH dis LIMIT 1
OPTIONAL MATCH (d:Drug)-[:TREATS]->(dis)
WITH dis, collect(DISTINCT d.name)[0..5] as treated_by
OPTIONAL MATCH (dis)-[:HAS_SYMPTOM]->(p:Phenotype)
RETURN dis.name as disease, treated_by, 
       collect(DISTINCT p.name)[0..5] as symptoms
```

### Python Neo4j Client Example
```python
from neo4j import GraphDatabase

class KnowledgeGraphService:
    def __init__(self, uri: str, user: str, password: str):
        self.driver = GraphDatabase.driver(uri, auth=(user, password))
    
    def check_drug_treats_disease(self, drug: str, disease: str) -> dict:
        query = """
        MATCH (d:Drug)-[r:TREATS]->(dis:Disease)
        WHERE toLower(d.name) CONTAINS toLower($drug)
          AND toLower(dis.name) CONTAINS toLower($disease)
        RETURN d.name as drug, dis.name as disease
        LIMIT 5
        """
        with self.driver.session() as session:
            result = session.run(query, drug=drug, disease=disease)
            records = [dict(r) for r in result]
            return {"found": len(records) > 0, "evidence": records}
    
    def close(self):
        self.driver.close()
```

---

# 5. API Specifications

## 5.1 Endpoints to Implement

### POST /verify
Main verification endpoint.

**Request:**
```json
{
  "text": "Aspirin is used to treat headaches and prevent heart attacks.",
  "options": {
    "check_contraindications": true,
    "check_side_effects": true,
    "include_evidence": true
  }
}
```

**Response:**
```json
{
  "success": true,
  "claims": [
    {
      "claim": "Aspirin treats headaches",
      "status": "SUPPORTED",
      "confidence": 0.92,
      "entities": [
        {"text": "Aspirin", "type": "Drug", "cui": "C0004057"},
        {"text": "headaches", "type": "Symptom", "cui": "C0018681"}
      ],
      "evidence": [
        {
          "source": "PrimeKG",
          "relationship": "TREATS",
          "drug": "Aspirin",
          "condition": "Headache"
        }
      ]
    },
    {
      "claim": "Aspirin prevents heart attacks",
      "status": "SUPPORTED",
      "confidence": 0.88,
      "entities": [
        {"text": "Aspirin", "type": "Drug", "cui": "C0004057"},
        {"text": "heart attacks", "type": "Disease", "cui": "C0027051"}
      ],
      "evidence": [
        {
          "source": "PrimeKG",
          "relationship": "TREATS",
          "drug": "Aspirin",
          "condition": "Myocardial Infarction"
        }
      ]
    }
  ],
  "warnings": [],
  "processing_time_ms": 245
}
```

### POST /extract
Entity extraction only (proxies to MedCAT).

**Request:**
```json
{
  "text": "Patient has diabetes and hypertension."
}
```

**Response:**
```json
{
  "entities": [
    {"text": "diabetes", "cui": "C0011847", "name": "Diabetes Mellitus", "type": "Disease"},
    {"text": "hypertension", "cui": "C0020538", "name": "Hypertensive disease", "type": "Disease"}
  ],
  "count": 2
}
```

### GET /drug/{drug_name}
Get drug information from knowledge graph.

**Response:**
```json
{
  "drug": "Metformin",
  "indications": ["Type 2 Diabetes", "Polycystic Ovary Syndrome"],
  "contraindications": ["Renal insufficiency", "Metabolic acidosis"],
  "side_effects": ["Nausea", "Diarrhea", "Lactic acidosis"],
  "interactions": ["Alcohol", "Iodinated contrast agents"]
}
```

### GET /disease/{disease_name}
Get disease information from knowledge graph.

**Response:**
```json
{
  "disease": "Type 2 Diabetes",
  "treatments": ["Metformin", "Insulin", "Glipizide"],
  "symptoms": ["Polyuria", "Polydipsia", "Fatigue", "Blurred vision"],
  "related_conditions": ["Obesity", "Metabolic syndrome"]
}
```

### GET /health
Health check endpoint.

**Response:**
```json
{
  "status": "healthy",
  "services": {
    "medcat": {"status": "up", "latency_ms": 45},
    "neo4j": {"status": "up", "latency_ms": 12}
  },
  "version": "1.0.0"
}
```

## 5.2 Verification Status Codes

| Status | Description |
|--------|-------------|
| `SUPPORTED` | Claim verified in knowledge graph |
| `CONTRADICTED` | Claim conflicts with knowledge graph (e.g., contraindication) |
| `NOT_FOUND` | Entities found but no relationship in graph |
| `PARTIAL` | Some claims verified, others not found |
| `UNKNOWN` | Could not extract meaningful entities |

## 5.3 Error Responses

```json
{
  "success": false,
  "error": {
    "code": "SERVICE_UNAVAILABLE",
    "message": "MedCAT service is not responding",
    "details": "Connection timeout after 30s"
  }
}
```

| Error Code | HTTP Status | Description |
|------------|-------------|-------------|
| `INVALID_INPUT` | 400 | Text is empty or too long |
| `SERVICE_UNAVAILABLE` | 503 | MedCAT or Neo4j is down |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Unexpected server error |

---

# 6. Database Schema

## 6.1 Neo4j Node Properties

### Drug Node
```
(:Drug {
  node_index: INTEGER,    // PrimeKG index
  node_id: STRING,        // DrugBank ID
  name: STRING,           // Drug name
  source: STRING          // Data source (DrugBank)
})
```

### Disease Node
```
(:Disease {
  node_index: INTEGER,
  node_id: STRING,        // MONDO/DO ID
  name: STRING,           // Disease name
  source: STRING          // Data source
})
```

### Phenotype/Effect Node
```
(:Phenotype {
  node_index: INTEGER,
  node_id: STRING,        // HPO ID
  name: STRING,           // Phenotype name
  source: STRING
})

(:Effect {
  node_index: INTEGER,
  node_id: STRING,
  name: STRING,
  source: STRING
})
```

## 6.2 Indexes
```cypher
CREATE INDEX FOR (n:Drug) ON (n.node_index);
CREATE INDEX FOR (n:Drug) ON (n.name);
CREATE INDEX FOR (n:Disease) ON (n.node_index);
CREATE INDEX FOR (n:Disease) ON (n.name);
CREATE INDEX FOR (n:Phenotype) ON (n.node_index);
CREATE INDEX FOR (n:Effect) ON (n.node_index);
```

## 6.3 Data Statistics

| Node Type | Count |
|-----------|-------|
| Drug | ~7,000 |
| Disease | ~17,000 |
| Gene | ~19,000 |
| Phenotype | ~500 |
| Effect | ~800 |
| **Total Nodes** | **44,316** |

| Relationship Type | Count |
|-------------------|-------|
| TREATS | ~18,776 |
| CONTRAINDICATED_FOR | ~61,350 |
| CAUSES_SIDE_EFFECT | ~129,568 |
| HAS_SYMPTOM | ~300,634 |
| INTERACTS_WITH | ~2,672,628 |
| **Total Relationships** | **2,426,257** |

---

# 7. Development Setup

## 7.1 Prerequisites
- Python 3.10+
- pip or uv package manager
- Git

## 7.2 Clone and Setup

```bash
# Clone repository
git clone <repository-url>
cd medclaimsverifier

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
```

## 7.3 Requirements File

```txt
# requirements.txt
fastapi==0.99.1
uvicorn[standard]==0.22.0
pydantic>=1.10.0,<2.0
python-dotenv==1.0.0
httpx==0.26.0
neo4j==5.16.0
loguru==0.7.2
pytest==7.4.4
pytest-asyncio==0.23.3
```

## 7.4 Environment Variables

Create `.env` file:
```bash
# .env
# MedCAT Service (Modal)
MEDCAT_API_URL=https://asmaamhadir--medcat-api-fastapi-app.modal.run

# Neo4j Aura
NEO4J_URI=neo4j+s://84b5974e.databases.neo4j.io
NEO4J_USER=neo4j
NEO4J_PASSWORD=ZnDSrk6RHNG-2ht5S45eg9chOd-anNA0Fbk19_59HQM

# API Settings
API_HOST=0.0.0.0
API_PORT=8000
LOG_LEVEL=INFO
```

## 7.5 Run Locally

```bash
# Start the API
uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# Test endpoints
curl http://localhost:8000/health
curl -X POST http://localhost:8000/extract \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient has diabetes"}'
```

---

# 8. Deployment Guide

## 8.1 Current Deployments

| Service | Platform | URL |
|---------|----------|-----|
| MedCAT API | Modal | https://asmaamhadir--medcat-api-fastapi-app.modal.run |
| Neo4j | Neo4j Aura | neo4j+s://84b5974e.databases.neo4j.io |
| Main API | TBD | TBD |

## 8.2 Modal Deployment (MedCAT)

The MedCAT service is already deployed. To redeploy:

```bash
# Login to Modal
modal setup

# Deploy
modal deploy modal_app.py

# View logs
modal app logs medcat-api
```

**Modal Volume:**
- Name: `medcat-model-vol`
- Contains: `medcat_model.zip` (963.5 MB)

## 8.3 Main API Deployment Options

### Option A: Railway (Recommended)
```bash
# Install Railway CLI
npm install -g @railway/cli

# Login and deploy
railway login
railway init
railway up
```

### Option B: Render
1. Connect GitHub repo to Render
2. Set environment variables
3. Deploy as Web Service

### Option C: Docker
```dockerfile
FROM python:3.10-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/

EXPOSE 8000

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

---

# 9. Development Roadmap

## Phase 1: Core API (Week 1-2) 🎯 CURRENT

### Tasks
- [ ] Set up project structure
- [ ] Implement MedCAT client service
- [ ] Implement Neo4j client service
- [ ] Build verification logic
- [ ] Create FastAPI endpoints
- [ ] Add error handling
- [ ] Write unit tests

### Deliverables
- Working `/verify` endpoint
- Working `/extract` endpoint
- Working `/drug/{name}` and `/disease/{name}` endpoints
- Health check endpoint

## Phase 2: Enhanced Verification (Week 3-4)

### Tasks
- [ ] Add claim extraction (identify specific claims in text)
- [ ] Implement confidence scoring algorithm
- [ ] Add support for negation in claims
- [ ] Handle complex multi-entity claims
- [ ] Add batch verification endpoint

### Deliverables
- Improved accuracy
- Batch processing capability
- Negation handling

## Phase 3: Production Hardening (Week 5-6)

### Tasks
- [ ] Add rate limiting
- [ ] Implement caching (Redis)
- [ ] Add authentication (API keys)
- [ ] Set up monitoring (Prometheus/Grafana)
- [ ] Add request logging
- [ ] Create admin dashboard

### Deliverables
- Production-ready API
- Monitoring dashboard
- API key management

## Phase 4: Advanced Features (Week 7-8)

### Tasks
- [ ] Add document upload (PDF processing)
- [ ] Implement contradiction detection
- [ ] Add source attribution
- [ ] Build simple web demo
- [ ] Create SDK (Python package)

### Deliverables
- Document verification
- Web demo
- Python SDK

---

# 10. Testing Guide

## 10.1 Test MedCAT Service

```bash
# Health check
curl https://asmaamhadir--medcat-api-fastapi-app.modal.run/health

# Extract entities
curl -X POST https://asmaamhadir--medcat-api-fastapi-app.modal.run/extract \
  -H "Content-Type: application/json" \
  -d '{"text": "Patient diagnosed with Type 2 Diabetes and prescribed Metformin."}'
```

Expected response:
```json
{
  "entities": [
    {"text": "Type 2 Diabetes", "cui": "...", "name": "Diabetes Mellitus, Type 2", ...},
    {"text": "Metformin", "cui": "C0025598", "name": "Metformin", ...}
  ],
  "count": 2
}
```

## 10.2 Test Neo4j Connection

```python
from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    "neo4j+s://84b5974e.databases.neo4j.io",
    auth=("neo4j", "ZnDSrk6RHNG-2ht5S45eg9chOd-anNA0Fbk19_59HQM")
)

with driver.session() as session:
    # Test connection
    result = session.run("RETURN 1 as test")
    print(result.single()["test"])  # Should print: 1
    
    # Test data
    result = session.run("""
        MATCH (d:Drug)-[:TREATS]->(dis:Disease)
        RETURN d.name as drug, dis.name as disease
        LIMIT 5
    """)
    for record in result:
        print(f"{record['drug']} TREATS {record['disease']}")

driver.close()
```

## 10.3 Test Queries

### Verify Metformin treats Diabetes
```cypher
MATCH (d:Drug)-[:TREATS]->(dis:Disease)
WHERE d.name CONTAINS 'Metformin' AND dis.name CONTAINS 'Diabetes'
RETURN d.name, dis.name
```

### Check Aspirin contraindications
```cypher
MATCH (d:Drug)-[:CONTRAINDICATED_FOR]->(dis:Disease)
WHERE d.name CONTAINS 'Aspirin'
RETURN d.name, dis.name
LIMIT 10
```

### Get all relationship types
```cypher
MATCH ()-[r]->()
RETURN type(r) as relationship, count(*) as count
ORDER BY count DESC
```

## 10.4 Sample Test Cases

| Input Text | Expected Result |
|------------|-----------------|
| "Metformin treats diabetes" | SUPPORTED |
| "Aspirin treats diabetes" | NOT_FOUND |
| "Patient has no diabetes" | Negation detected |
| "Ibuprofen may cause stomach bleeding" | SUPPORTED (side effect) |
| "Penicillin is contraindicated in penicillin allergy" | SUPPORTED (contraindication) |

---

# 11. Appendix

## 11.1 Useful Links

| Resource | URL |
|----------|-----|
| MedCAT Documentation | https://github.com/CogStack/MedCAT |
| PrimeKG Paper | https://www.nature.com/articles/s41597-023-01960-3 |
| Neo4j Cypher Manual | https://neo4j.com/docs/cypher-manual/ |
| FastAPI Documentation | https://fastapi.tiangolo.com/ |
| Modal Documentation | https://modal.com/docs |

## 11.2 SNOMED-CT Semantic Types

| Code | Type |
|------|------|
| T047 | Disease or Syndrome |
| T184 | Sign or Symptom |
| T121 | Pharmacologic Substance |
| T109 | Organic Chemical |
| T023 | Body Part |
| T028 | Gene or Genome |

## 11.3 PrimeKG Data Sources

- DrugBank (drugs, interactions)
- MONDO (disease ontology)
- HPO (phenotypes)
- Reactome (pathways)
- DisGeNET (gene-disease associations)
- SIDER (side effects)

## 11.4 Troubleshooting

### MedCAT Cold Start
First request after 5+ minutes of inactivity takes ~30-60 seconds. This is normal (Modal container spinning up).

### Neo4j Connection Timeout
If Neo4j queries timeout:
```python
# Increase timeout
driver = GraphDatabase.driver(
    uri, auth=(user, password),
    connection_timeout=30,
    max_transaction_retry_time=30
)
```

### Entity Not Found in Graph
Not all MedCAT entities have corresponding nodes in PrimeKG. Handle gracefully:
```python
if not kg_result["found"]:
    return VerificationStatus.NOT_FOUND
```

---

## Contact & Support

- **Project Owner**: Asmaa
- **Modal Dashboard**: https://modal.com/apps/asmaamhadir/main/deployed/medcat-api
- **Neo4j Console**: https://console.neo4j.io

---

*Document Version: 1.0*
*Last Updated: January 2, 2026*
