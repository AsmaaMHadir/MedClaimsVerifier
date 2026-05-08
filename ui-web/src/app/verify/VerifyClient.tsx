"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type {
  GraphEdge,
  GraphNode,
  VerifyResponse,
} from "@/types/medverify";
import { EntityChip } from "@/components/verify/EntityChip";
import { HighlightedClaim } from "@/components/verify/HighlightedClaim";
import { VerdictCard } from "@/components/verify/VerdictCard";
import { EvidenceTable } from "@/components/verify/EvidenceTable";
import { Subgraph } from "@/components/graph/Subgraph";
import { GraphLegend } from "@/components/graph/GraphLegend";
import { fromClaim, mergeGraphs } from "@/components/graph/graphTransforms";

export function VerifyClient() {
  const params = useSearchParams();
  const initial = params.get("claim") ?? "";
  const auto = params.get("auto") === "1";

  const [text, setText] = useState(initial);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<VerifyResponse | null>(null);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({
    nodes: [],
    edges: [],
  });
  const autoRan = useRef(false);

  const onSubmit = async (claim: string) => {
    if (!claim.trim()) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    setGraph({ nodes: [], edges: [] });
    try {
      const res = await api.verify(claim);
      setResponse(res);
      const merged = res.claims.reduce(
        (acc, c) => mergeGraphs(acc, fromClaim(c)),
        { nodes: [], edges: [] } as { nodes: GraphNode[]; edges: GraphEdge[] }
      );
      setGraph(merged);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (auto && initial && !autoRan.current) {
      autoRan.current = true;
      onSubmit(initial);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [auto, initial]);

  const onNodeClick = async (node: GraphNode) => {
    if (node.type !== "Drug" && node.type !== "Disease") return;
    try {
      const nb = await api.getNeighborhood(
        node.type as "Drug" | "Disease",
        node.name,
        8
      );
      setGraph((g) => mergeGraphs(g, nb));
    } catch (e) {
      console.warn("Neighborhood fetch failed", e);
    }
  };

  const allEntities = useMemo(
    () => response?.claims.flatMap((c) => c.entities) ?? [],
    [response]
  );

  return (
    <div className="flex flex-col gap-12">
      <header>
        <h1 className="font-serif text-4xl tracking-tightish text-ink">
          Check a medical statement
        </h1>
        <p className="mt-3 max-w-2xl text-ink-muted">
          We identify the medical terms in your text and check the
          relationships between them against clinical evidence.
        </p>
      </header>

      <section className="card p-5">
        <textarea
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="e.g. Metformin treats Type 2 Diabetes"
          rows={3}
          className="input resize-none"
        />
        <div className="mt-3 flex items-center justify-end gap-2">
          <button
            className="btn-ghost"
            onClick={() => {
              setText("");
              setResponse(null);
              setError(null);
              setGraph({ nodes: [], edges: [] });
            }}
          >
            Clear
          </button>
          <button
            className="btn-primary px-6 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={() => onSubmit(text)}
            disabled={loading || !text.trim()}
          >
            {loading ? "Checking…" : "Check claim"}
          </button>
        </div>
      </section>

      {error && (
        <div className="card border-verdict-contradicted/40 bg-verdict-contradicted/8 p-4 text-sm text-verdict-contradicted">
          {error}
        </div>
      )}

      {response && (
        <section className="flex flex-col gap-10">
          <div className="card p-6">
            <p className="eyebrow">Statement</p>
            <div className="mt-3">
              <HighlightedClaim text={text} entities={allEntities} />
            </div>
            {allEntities.length > 0 && (
              <div className="mt-5 flex flex-wrap gap-2">
                {allEntities.map((e, i) => (
                  <EntityChip key={`${e.text}-${i}`} entity={e} />
                ))}
              </div>
            )}
          </div>

          <div>
            <p className="eyebrow mb-4">Verdict</p>
            <div className="grid gap-4 lg:grid-cols-2">
              {response.claims.map((c, i) => (
                <VerdictCard key={i} claim={c} />
              ))}
            </div>
          </div>

          <div>
            <p className="eyebrow mb-4">Evidence</p>
            <EvidenceTable evidence={response.claims.flatMap((c) => c.evidence)} />
          </div>

          <div>
            <div className="mb-4 flex items-center justify-between">
              <p className="eyebrow">Connected context</p>
              <GraphLegend />
            </div>
            <Subgraph
              nodes={graph.nodes}
              edges={graph.edges}
              height={460}
              onNodeClick={onNodeClick}
            />
          </div>
        </section>
      )}
    </div>
  );
}
