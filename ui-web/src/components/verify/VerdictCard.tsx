import type { ClaimVerification } from "@/types/medverify";
import { STATUS_STYLES } from "@/lib/statusStyles";

const PREDICATE_LABEL: Record<string, string> = {
  TREATS: "treats",
  CAUSES_SIDE_EFFECT: "may cause",
  CONTRAINDICATED_FOR: "is contraindicated for",
  INTERACTS_WITH: "interacts with",
  HAS_SYMPTOM: "presents with",
};

function pretty(p?: string | null): string {
  if (!p) return "—";
  return PREDICATE_LABEL[p] ?? p.toLowerCase().replace(/_/g, " ");
}

export function VerdictCard({ claim }: { claim: ClaimVerification }) {
  const s = STATUS_STYLES[claim.status];
  const pct = Math.round((claim.confidence ?? 0) * 100);
  const showRelationRow =
    claim.asserted_predicate &&
    (claim.evidence_predicate ||
      claim.status === "NOT_FOUND" ||
      claim.status === "CONTRADICTED");

  return (
    <div className={`card p-6 border ${s.border}`}>
      <div className="flex items-start justify-between gap-4">
        <div className="min-w-0">
          <span className={`pill border ${s.border} ${s.bg} ${s.color}`}>
            <span className="h-1.5 w-1.5 rounded-full bg-current" />
            {s.label}
          </span>
          <h3 className="mt-3 font-serif text-xl leading-snug text-ink">
            {claim.claim}
          </h3>
          <p className="mt-2 max-w-prose text-sm text-ink-muted">
            {claim.explanation ?? s.description}
          </p>

          {showRelationRow && (
            <div className="mt-4 grid grid-cols-2 gap-x-6 gap-y-1 text-xs">
              <div>
                <div className="eyebrow">You asserted</div>
                <div className="mt-1 font-mono text-ink">
                  {pretty(claim.asserted_predicate)}
                  {claim.negated && (
                    <span className="ml-1 text-verdict-contradicted">(negated)</span>
                  )}
                </div>
              </div>
              <div>
                <div className="eyebrow">Evidence shows</div>
                <div className="mt-1 font-mono text-ink">
                  {pretty(claim.evidence_predicate)}
                </div>
              </div>
            </div>
          )}
        </div>

        <div className="text-right shrink-0">
          <div className="eyebrow">Confidence</div>
          <div className={`mt-1 font-serif text-3xl ${s.color}`}>{pct}%</div>
        </div>
      </div>
    </div>
  );
}
