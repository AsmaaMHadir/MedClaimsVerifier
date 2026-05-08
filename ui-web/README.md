# MedVerify — Showcase UI (Next.js)

A polished portfolio UI for the MedVerify API. Sits next to the existing Streamlit
UI in `../ui/` and exercises every API capability:

- `POST /verify` — claim verification with highlighted entities, verdict cards,
  evidence rows, and an interactive subgraph
- `POST /extract` — GLiNER entity extraction playground with confidence bars
- `GET /search` — free-text knowledge graph explorer
- `GET /drug/{name}` and `GET /disease/{name}` — entity profiles with neighborhood graph
- `GET /neighborhood/{type}/{name}` — click-to-expand graph exploration
- `GET /health` — lightweight status pill in the topbar

## Run

```bash
# 1. Backend (in another terminal)
cd ..
source venv/bin/activate
uvicorn src.main:app --reload --port 8000

# 2. Frontend
cp .env.local.example .env.local
npm install
npm run dev    # http://localhost:3000
```

## Configuration

| Variable | Purpose | Default |
|---|---|---|
| `NEXT_PUBLIC_MEDVERIFY_API_URL` | Backend base URL | `http://localhost:8000` |
| `NEXT_PUBLIC_MEDVERIFY_API_KEY` | Optional `X-API-Key` header | _(empty)_ |

> **Security note:** any `NEXT_PUBLIC_*` value ships to the browser. For a real
> deployment, proxy through a Next.js Route Handler that injects the key
> server-side instead of exposing it to clients.

## Stack

- Next.js 14 (App Router) + React 18 + TypeScript
- Tailwind CSS for styling (dark theme tuned for KG demos)
- `react-force-graph-2d` for the subgraph canvas (dynamic import, `ssr: false`)

## Layout

```
src/
├─ app/
│  ├─ layout.tsx                # Topbar + HealthPill + global shell
│  ├─ page.tsx                  # Landing + curated example cards
│  ├─ verify/                   # POST /verify flow
│  ├─ extract/                  # POST /extract playground
│  ├─ explorer/                 # GET /search
│  ├─ drug/[name]/              # GET /drug + /neighborhood
│  └─ disease/[name]/           # GET /disease + /neighborhood
├─ components/
│  ├─ layout/                   # Topbar, HealthPill, Footer
│  ├─ verify/                   # ClaimInput, VerdictCard, EntityChip, EvidenceTable…
│  ├─ profile/                  # FactList, EntityProfile
│  └─ graph/                    # Subgraph, GraphLegend, graphTransforms
├─ lib/
│  ├─ api.ts                    # typed fetch wrapper
│  ├─ examples.ts               # curated showcase claims
│  ├─ statusStyles.ts           # verdict → color/border
│  └─ entityColors.ts           # entity type → color
├─ types/medverify.ts           # mirrors src/models/responses.py
└─ hooks/useDebounced.ts
```

## Build

```bash
npm run build
npm run start
```

## End-to-end smoke test

With both backend and frontend running:

1. Home → click any verdict card → `/verify?claim=...&auto=1` runs automatically.
2. `/verify` → for each verdict type: chips align with source via offsets,
   verdict color matches status, evidence rows link to drug/disease profiles,
   subgraph renders, clicking a node expands its neighborhood.
3. `/extract` → confidence-bar chips + JSON pane for raw response.
4. `/explorer` → debounced search; results route to profile pages.
5. `/drug/metformin`, `/disease/diabetes` → fact lists + neighborhood graph; clicking
   another drug/disease node navigates to that profile.
