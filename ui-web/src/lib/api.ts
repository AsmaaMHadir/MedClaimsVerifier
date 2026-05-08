import type {
  DiseaseInfo,
  DrugInfo,
  ExtractResponse,
  HealthResponse,
  NeighborhoodResponse,
  SearchResponse,
  VerifyResponse,
} from "@/types/medverify";

const BASE =
  process.env.NEXT_PUBLIC_MEDVERIFY_API_URL?.replace(/\/$/, "") ??
  "http://localhost:8000";

const KEY = process.env.NEXT_PUBLIC_MEDVERIFY_API_KEY ?? "";

class ApiError extends Error {
  status: number;
  body: unknown;
  constructor(status: number, body: unknown, message: string) {
    super(message);
    this.status = status;
    this.body = body;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  if (init?.body && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (KEY) headers.set("X-API-Key", KEY);

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
    cache: "no-store",
  });

  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }

  if (!res.ok) {
    const detail =
      typeof body === "object" && body !== null && "detail" in body
        ? (body as { detail: unknown }).detail
        : body;
    const message =
      typeof detail === "object" && detail !== null && "message" in detail
        ? String((detail as { message: unknown }).message)
        : `Request failed (${res.status})`;
    throw new ApiError(res.status, body, message);
  }

  return body as T;
}

export const api = {
  baseUrl: BASE,
  hasApiKey: Boolean(KEY),

  verify: (text: string) =>
    request<VerifyResponse>("/verify", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  extract: (text: string) =>
    request<ExtractResponse>("/extract", {
      method: "POST",
      body: JSON.stringify({ text }),
    }),

  getDrug: (name: string) =>
    request<DrugInfo>(`/drug/${encodeURIComponent(name)}`),

  getDisease: (name: string) =>
    request<DiseaseInfo>(`/disease/${encodeURIComponent(name)}`),

  search: (q: string, type?: string) => {
    const params = new URLSearchParams({ q });
    if (type) params.set("type", type);
    return request<SearchResponse>(`/search?${params.toString()}`);
  },

  getNeighborhood: (
    entityType: "Drug" | "Disease",
    name: string,
    limit = 5
  ) =>
    request<NeighborhoodResponse>(
      `/neighborhood/${entityType}/${encodeURIComponent(name)}?limit=${limit}`
    ),

  getHealth: () => request<HealthResponse>("/health"),
};

export { ApiError };
