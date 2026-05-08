"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { api, ApiError } from "@/lib/api";
import { useDebounced } from "@/hooks/useDebounced";
import type { SearchResponse } from "@/types/medverify";
import { styleForEntity } from "@/lib/entityColors";

const TYPES = [
  { value: "", label: "All" },
  { value: "Drug", label: "Drugs" },
  { value: "Disease", label: "Conditions" },
  { value: "Phenotype", label: "Symptoms" },
  { value: "Effect", label: "Side effects" },
];

export default function ExplorerPage() {
  const [q, setQ] = useState("diabet");
  const [type, setType] = useState("");
  const dq = useDebounced(q, 350);
  const [data, setData] = useState<SearchResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (dq.trim().length < 2) {
      setData(null);
      return;
    }
    let alive = true;
    setLoading(true);
    setError(null);
    api
      .search(dq, type || undefined)
      .then((res) => {
        if (alive) setData(res);
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
  }, [dq, type]);

  return (
    <div className="flex flex-col gap-12">
      <header>
        <h1 className="font-serif text-4xl tracking-tightish text-ink">
          Browse the medical knowledge base
        </h1>
        <p className="mt-3 max-w-2xl text-ink-muted">
          Search drugs, conditions, symptoms, and side effects. Open any entry
          to see what it&apos;s connected to.
        </p>
      </header>

      <section className="card p-4">
        <div className="flex flex-col gap-3 sm:flex-row">
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search the knowledge base…"
            className="input flex-1"
          />
          <select
            value={type}
            onChange={(e) => setType(e.target.value)}
            className="input sm:max-w-[200px]"
          >
            {TYPES.map((t) => (
              <option key={t.value} value={t.value}>
                {t.label}
              </option>
            ))}
          </select>
        </div>
      </section>

      {error && (
        <div className="card border-verdict-contradicted/40 bg-verdict-contradicted/8 p-4 text-sm text-verdict-contradicted">
          {error}
        </div>
      )}

      {loading && <p className="text-sm text-ink-muted">Searching…</p>}

      {data && data.results.length === 0 && !loading && (
        <p className="text-sm text-ink-muted">No matches.</p>
      )}

      {data && data.results.length > 0 && (
        <ul className="grid gap-px bg-rule sm:grid-cols-2">
          {data.results.map((r, i) => {
            const isDrug = r.labels?.includes("Drug");
            const isDisease = r.labels?.includes("Disease");
            const href = isDrug
              ? `/drug/${encodeURIComponent(r.name)}`
              : isDisease
              ? `/disease/${encodeURIComponent(r.name)}`
              : null;

            const card = (
              <div
                className={`flex h-full items-center justify-between gap-3 bg-bg-elevated p-4 transition-colors hover:bg-bg-subtle ${
                  href ? "cursor-pointer" : ""
                }`}
              >
                <div>
                  <div className="font-serif text-base text-ink">{r.name}</div>
                  <div className="mt-1 flex flex-wrap gap-1.5">
                    {r.labels?.map((lbl) => {
                      const ls = styleForEntity(lbl);
                      return (
                        <span
                          key={lbl}
                          className={`pill border ${ls.border} ${ls.bg} ${ls.color}`}
                        >
                          {ls.label}
                        </span>
                      );
                    })}
                  </div>
                </div>
                {href && (
                  <span className="text-xs text-accent shrink-0">Open →</span>
                )}
              </div>
            );
            return (
              <li key={`${r.name}-${i}`}>
                {href ? <Link href={href}>{card}</Link> : card}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
