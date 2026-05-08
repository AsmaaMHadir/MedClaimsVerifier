import type {
  ClaimVerification,
  Entity,
  Evidence,
  GraphEdge,
  GraphNode,
} from "@/types/medverify";

interface GraphData {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export function fromClaim(claim: ClaimVerification): GraphData {
  const nodes = new Map<string, GraphNode>();
  const edges: GraphEdge[] = [];

  for (const e of claim.entities) {
    const id = e.name || e.text;
    if (!id) continue;
    if (!nodes.has(id)) {
      nodes.set(id, { id, name: id, type: e.type, text: e.text });
    }
  }

  for (const ev of claim.evidence) {
    const subj = ev.subject;
    const obj = ev.object;
    if (!subj || !obj) continue;
    if (!nodes.has(subj))
      nodes.set(subj, { id: subj, name: subj, type: "Drug" });
    if (!nodes.has(obj))
      nodes.set(obj, { id: obj, name: obj, type: typeFromRel(ev.relationship) });
    edges.push({ source: subj, target: obj, relationship: ev.relationship });
  }

  return { nodes: Array.from(nodes.values()), edges };
}

function typeFromRel(rel: string): string {
  if (rel === "TREATS" || rel === "CONTRAINDICATED_FOR") return "Disease";
  if (rel === "CAUSES_SIDE_EFFECT") return "Effect";
  if (rel === "HAS_SYMPTOM") return "Phenotype";
  if (rel === "INTERACTS_WITH") return "Drug";
  return "Entity";
}

export function fromEntities(entities: Entity[], evidence: Evidence[]): GraphData {
  return fromClaim({
    claim: "",
    status: "UNKNOWN",
    confidence: 0,
    entities,
    evidence,
  });
}

export function mergeGraphs(a: GraphData, b: GraphData): GraphData {
  const nodes = new Map<string, GraphNode>();
  for (const n of a.nodes) nodes.set(n.id, n);
  for (const n of b.nodes) if (!nodes.has(n.id)) nodes.set(n.id, n);

  const seenEdge = new Set<string>();
  const edges: GraphEdge[] = [];
  for (const e of [...a.edges, ...b.edges]) {
    const key = `${e.source}->${e.target}:${e.relationship}`;
    if (seenEdge.has(key)) continue;
    seenEdge.add(key);
    edges.push(e);
  }

  return { nodes: Array.from(nodes.values()), edges };
}
