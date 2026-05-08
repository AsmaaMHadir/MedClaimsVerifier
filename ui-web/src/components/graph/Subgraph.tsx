"use client";

import dynamic from "next/dynamic";
import { useMemo } from "react";
import type { GraphEdge, GraphNode } from "@/types/medverify";
import { colorForType } from "@/lib/entityColors";

// react-force-graph-2d's types are loose and it touches `window`,
// so we dynamic-import without SSR and treat the component as `any`.
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const ForceGraph2D: any = dynamic(() => import("react-force-graph-2d"), {
  ssr: false,
  loading: () => (
    <div className="grid h-full place-items-center text-sm text-ink-dim">
      Loading…
    </div>
  ),
});

interface Props {
  nodes: GraphNode[];
  edges: GraphEdge[];
  height?: number;
  onNodeClick?: (node: GraphNode) => void;
  highlightId?: string;
}

interface FGNode extends GraphNode {
  __color: string;
  __highlight: boolean;
  x?: number;
  y?: number;
}

interface FGLink {
  source: string;
  target: string;
  relationship: string;
}

export function Subgraph({
  nodes,
  edges,
  height = 420,
  onNodeClick,
  highlightId,
}: Props) {
  const data = useMemo(() => {
    const fgNodes: FGNode[] = nodes.map((n) => ({
      ...n,
      __color: colorForType(n.type),
      __highlight: highlightId === n.id,
    }));
    const fgLinks: FGLink[] = edges.map((e) => ({
      source: e.source,
      target: e.target,
      relationship: e.relationship,
    }));
    return { nodes: fgNodes, links: fgLinks };
  }, [nodes, edges, highlightId]);

  if (nodes.length === 0) {
    return (
      <div
        className="card grid place-items-center text-sm text-ink-dim"
        style={{ height }}
      >
        Nothing to show.
      </div>
    );
  }

  return (
    <div className="card overflow-hidden" style={{ height }}>
      <ForceGraph2D
        graphData={data}
        height={height}
        backgroundColor="rgba(0,0,0,0)"
        cooldownTicks={60}
        nodeRelSize={5}
        linkColor={() => "rgba(91,87,81,0.35)"}
        linkDirectionalArrowLength={4}
        linkDirectionalArrowRelPos={1}
        linkCurvature={0.08}
        linkLabel={(l: FGLink) => l.relationship}
        nodeLabel={(n: FGNode) => `${n.name} (${n.type})`}
        nodeCanvasObject={(
          node: FGNode,
          ctx: CanvasRenderingContext2D,
          scale: number
        ) => {
          const r = node.__highlight ? 7 : 5;
          ctx.beginPath();
          ctx.arc(node.x ?? 0, node.y ?? 0, r, 0, 2 * Math.PI, false);
          ctx.fillStyle = node.__color;
          ctx.fill();
          if (node.__highlight) {
            ctx.lineWidth = 2 / scale;
            ctx.strokeStyle = "#101512";
            ctx.stroke();
          }
          const fontSize = 11 / scale;
          ctx.font = `${fontSize}px Inter, system-ui, sans-serif`;
          ctx.textAlign = "center";
          ctx.textBaseline = "top";
          ctx.fillStyle = "#101512";
          ctx.fillText(node.name, node.x ?? 0, (node.y ?? 0) + r + 2);
        }}
        onNodeClick={(node: FGNode) => onNodeClick?.(node)}
      />
    </div>
  );
}
