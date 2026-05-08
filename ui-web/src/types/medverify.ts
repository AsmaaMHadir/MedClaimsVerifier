export type VerificationStatus =
  | "SUPPORTED"
  | "CONTRADICTED"
  | "NOT_FOUND"
  | "PARTIAL"
  | "UNKNOWN";

export interface Entity {
  text: string;
  cui: string;
  name: string;
  type: string;
  confidence: number;
  start?: number | null;
  end?: number | null;
  negated: boolean;
  // Normalization (e.g. brand → generic). Populated only when needed.
  normalized_name?: string | null;
  normalized_ingredients?: string[];
  normalization_source?: string | null;
  normalization_score?: number | null;
  normalization_id?: string | null;
}

export interface Evidence {
  source: string;
  relationship: string;
  subject: string;
  object: string;
}

export interface ClaimVerification {
  claim: string;
  status: VerificationStatus;
  confidence: number;
  entities: Entity[];
  evidence: Evidence[];
  asserted_predicate?: string | null;
  evidence_predicate?: string | null;
  negated?: boolean;
  explanation?: string | null;
}

export interface VerifyResponse {
  success: boolean;
  claims: ClaimVerification[];
  warnings: string[];
  processing_time_ms: number;
}

export interface ExtractResponse {
  success: boolean;
  entities: Entity[];
  count: number;
}

export interface DrugInfo {
  drug: string;
  indications: string[];
  contraindications: string[];
  side_effects: string[];
  interactions: string[];
}

export interface DiseaseInfo {
  disease: string;
  treatments: string[];
  symptoms: string[];
  related_conditions: string[];
}

export interface GraphNode {
  id: string;
  name: string;
  type: string;
  text?: string | null;
}

export interface GraphEdge {
  source: string;
  target: string;
  relationship: string;
}

export interface NeighborhoodResponse {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface SearchResultItem {
  name: string;
  id: string | number | null;
  labels: string[];
}

export interface SearchResponse {
  query: string;
  type_filter: string | null;
  results: SearchResultItem[];
  count: number;
}

export interface HealthResponse {
  status: "healthy" | "degraded" | "unhealthy" | string;
  services: Record<string, Record<string, unknown>>;
  version: string;
}
