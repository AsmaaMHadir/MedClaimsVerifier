"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { api, ApiError } from "@/lib/api";
import type {
  DiseaseInfo,
  DrugInfo,
  GraphEdge,
  GraphNode,
} from "@/types/medverify";
import { FactList } from "./FactList";
import { Subgraph } from "@/components/graph/Subgraph";
import { GraphLegend } from "@/components/graph/GraphLegend";
import { mergeGraphs } from "@/components/graph/graphTransforms";
import { styleForEntity } from "@/lib/entityColors";

interface Props {
  name: string;
  kind: "Drug" | "Disease";
}

export function EntityProfile({ name, kind }: Props) {
  const router = useRouter();
  const [info, setInfo] = useState<DrugInfo | DiseaseInfo | null>(null);
  const [graph, setGraph] = useState<{ nodes: GraphNode[]; edges: GraphEdge[] }>({
    nodes: [],
    edges: [],
  });
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    setError(null);
    setInfo(null);
    setGraph({ nodes: [], edges: [] });

    const infoPromise = kind === "Drug" ? api.getDrug(name) : api.getDisease(name);
    Promise.all([infoPromise, api.getNeighborhood(kind, name, 12)])
      .then(([i, n]) => {
        if (!alive) return;
        setInfo(i);
        setGraph(n);
      })
      .catch((e) => {
        if (!alive) return;
        const msg = e instanceof ApiError ? e.message : (e as Error).message;
        setError(msg);
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, [name, kind]);

  const onNodeClick = async (node: GraphNode) => {
    if (node.type === "Drug" && node.name !== name) {
      router.push(`/drug/${encodeURIComponent(node.name)}`);
      return;
    }
    if (node.type === "Disease" && node.name !== name) {
      router.push(`/disease/${encodeURIComponent(node.name)}`);
      return;
    }
    if (node.type !== "Drug" && node.type !== "Disease") return;
    try {
      const nb = await api.getNeighborhood(node.type as "Drug" | "Disease", node.name, 8);
      setGraph((g) => mergeGraphs(g, nb));
    } catch (e) {
      console.warn("Neighborhood fetch failed", e);
    }
  };

  const s = styleForEntity(kind);

  return (
    <div className="flex flex-col gap-12">
      <header>
        <span className={`pill border ${s.border} ${s.bg} ${s.color}`}>
          <span className="h-1.5 w-1.5 rounded-full bg-current" />
          {kind === "Drug" ? "Drug" : "Condition"}
        </span>
        <h1 className="mt-3 font-serif text-4xl tracking-tighter2 text-ink">
          {name}
        </h1>
      </header>

      {loading && <p className="text-sm text-ink-muted">Loading…</p>}

      {error && (
        <div className="card border-verdict-contradicted/40 bg-verdict-contradicted/8 p-4 text-sm text-verdict-contradicted">
          {error}
        </div>
      )}

      {info && kind === "Drug" && "drug" in info && (
        <section className="grid gap-4 md:grid-cols-2">
          <FactList
            title="Used to treat"
            items={(info as DrugInfo).indications}
            href={(n) => `/disease/${encodeURIComponent(n)}`}
            accent="text-verdict-supported"
          />
          <FactList
            title="Avoid in"
            items={(info as DrugInfo).contraindications}
            href={(n) => `/disease/${encodeURIComponent(n)}`}
            accent="text-verdict-contradicted"
          />
          <FactList
            title="Possible side effects"
            items={(info as DrugInfo).side_effects}
            accent="text-entity-effect"
          />
          <FactList
            title="Interacts with"
            items={(info as DrugInfo).interactions}
            href={(n) => `/drug/${encodeURIComponent(n)}`}
            accent="text-verdict-notfound"
          />
        </section>
      )}

      {info && kind === "Disease" && "disease" in info && (
        <section className="grid gap-4 md:grid-cols-2">
          <FactList
            title="Treated by"
            items={(info as DiseaseInfo).treatments}
            href={(n) => `/drug/${encodeURIComponent(n)}`}
            accent="text-verdict-supported"
          />
          <FactList
            title="Common symptoms"
            items={(info as DiseaseInfo).symptoms}
            accent="text-entity-symptom"
          />
          <FactList
            title="Related conditions"
            items={(info as DiseaseInfo).related_conditions}
            href={(n) => `/disease/${encodeURIComponent(n)}`}
            accent="text-entity-disease"
          />
        </section>
      )}

      {graph.nodes.length > 0 && (
        <section>
          <div className="mb-4 flex items-center justify-between">
            <p className="eyebrow">Connected context</p>
            <GraphLegend />
          </div>
          <Subgraph
            nodes={graph.nodes}
            edges={graph.edges}
            height={460}
            highlightId={name}
            onNodeClick={onNodeClick}
          />
        </section>
      )}
    </div>
  );
}
