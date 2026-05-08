"use client";

import { useState } from "react";
import { api, ApiError } from "@/lib/api";
import type { ExtractResponse } from "@/types/medverify";
import { EntityChip } from "@/components/verify/EntityChip";
import { HighlightedClaim } from "@/components/verify/HighlightedClaim";

const EXAMPLES = [
  "Patient takes Metformin for diabetes and reports occasional nausea.",
  "No evidence of heart failure or hypertension on examination.",
  "Started lisinopril; consider adding atorvastatin for hyperlipidemia.",
];

export default function ExtractPage() {
  const [text, setText] = useState(EXAMPLES[0]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<ExtractResponse | null>(null);

  const onExtract = async () => {
    if (!text.trim()) return;
    setLoading(true);
    setError(null);
    setResponse(null);
    try {
      const res = await api.extract(text);
      setResponse(res);
    } catch (e) {
      const msg = e instanceof ApiError ? e.message : (e as Error).message;
      setError(msg);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="flex flex-col gap-12">
      <header>
        <h1 className="font-serif text-4xl tracking-tightish text-ink">
          Pull medical terms from any text
        </h1>
        <p className="mt-3 max-w-2xl text-ink-muted">
          See the <span className="text-entity-drug font-medium">drugs</span>,{" "}
          <span className="text-entity-disease font-medium">conditions</span>,
          and <span className="text-entity-symptom font-medium">symptoms</span>{" "}
          recognised in your text, including negated mentions like “no
          evidence of…”.
        </p>
      </header>

      <section className="card p-5">
        <textarea
          rows={4}
          value={text}
          onChange={(e) => setText(e.target.value)}
          className="input resize-none"
          placeholder="Paste a clinical sentence…"
        />
        <div className="mt-3 flex flex-wrap items-center justify-between gap-2">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-xs text-ink-dim">Examples:</span>
            {EXAMPLES.map((ex, i) => (
              <button
                key={i}
                className="rounded border border-rule bg-bg px-2 py-1 text-xs text-ink-muted hover:bg-bg-subtle hover:text-ink"
                onClick={() => setText(ex)}
              >
                #{i + 1}
              </button>
            ))}
          </div>
          <button
            className="btn-primary px-6 disabled:cursor-not-allowed disabled:opacity-50"
            onClick={onExtract}
            disabled={loading || !text.trim()}
          >
            {loading ? "Identifying…" : "Identify terms"}
          </button>
        </div>
      </section>

      {error && (
        <div className="card border-verdict-contradicted/40 bg-verdict-contradicted/8 p-4 text-sm text-verdict-contradicted">
          {error}
        </div>
      )}

      {response && (
        <section className="grid gap-6 lg:grid-cols-2">
          <div className="card p-6">
            <p className="eyebrow">Highlighted text</p>
            <div className="mt-3">
              <HighlightedClaim text={text} entities={response.entities} />
            </div>
            {response.entities.length > 0 ? (
              <div className="mt-5 flex flex-wrap gap-2">
                {response.entities.map((e, i) => (
                  <EntityChip key={i} entity={e} />
                ))}
              </div>
            ) : (
              <p className="mt-4 text-sm text-ink-muted">
                No medical terms recognised.
              </p>
            )}
            <div className="mt-4 text-xs text-ink-dim">
              {response.count} term{response.count === 1 ? "" : "s"} recognised
            </div>
          </div>

          <div className="card overflow-hidden">
            <div className="border-b border-rule px-5 py-3">
              <p className="eyebrow">Details</p>
            </div>
            <pre className="max-h-[440px] overflow-auto bg-bg-subtle/40 p-5 font-mono text-xs leading-relaxed text-ink">
{JSON.stringify(response.entities, null, 2)}
            </pre>
          </div>
        </section>
      )}
    </div>
  );
}
