import Link from "next/link";
import type { Evidence } from "@/types/medverify";

const REL_LABELS: Record<string, string> = {
  TREATS: "treats",
  CONTRAINDICATED_FOR: "contraindicated for",
  CAUSES_SIDE_EFFECT: "may cause",
  HAS_SYMPTOM: "has symptom",
  INTERACTS_WITH: "interacts with",
  OFF_LABEL_FOR: "off-label for",
};

function profileHref(name: string, rel: string, role: "subject" | "object") {
  if (role === "subject" && rel !== "HAS_SYMPTOM")
    return `/drug/${encodeURIComponent(name)}`;
  if (role === "subject" && rel === "HAS_SYMPTOM")
    return `/disease/${encodeURIComponent(name)}`;
  if (rel === "INTERACTS_WITH") return `/drug/${encodeURIComponent(name)}`;
  if (rel === "TREATS" || rel === "CONTRAINDICATED_FOR")
    return `/disease/${encodeURIComponent(name)}`;
  return null;
}

export function EvidenceTable({ evidence }: { evidence: Evidence[] }) {
  if (evidence.length === 0) {
    return (
      <div className="card p-5 text-sm text-ink-muted">
        No supporting evidence on record for this claim.
      </div>
    );
  }
  return (
    <div className="card overflow-hidden">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-rule text-left">
            <th className="px-5 py-3 eyebrow font-semibold">Subject</th>
            <th className="px-5 py-3 eyebrow font-semibold">Relationship</th>
            <th className="px-5 py-3 eyebrow font-semibold">Object</th>
          </tr>
        </thead>
        <tbody>
          {evidence.map((e, i) => {
            const subjHref = profileHref(e.subject, e.relationship, "subject");
            const objHref = profileHref(e.object, e.relationship, "object");
            return (
              <tr
                key={i}
                className={`${i > 0 ? "border-t border-rule" : ""} hover:bg-bg-subtle/60`}
              >
                <td className="px-5 py-3 font-medium text-ink">
                  {subjHref ? (
                    <Link className="text-accent hover:underline" href={subjHref}>
                      {e.subject}
                    </Link>
                  ) : (
                    e.subject
                  )}
                </td>
                <td className="px-5 py-3 text-ink-muted">
                  {REL_LABELS[e.relationship] ?? e.relationship.toLowerCase()}
                </td>
                <td className="px-5 py-3 font-medium text-ink">
                  {objHref ? (
                    <Link className="text-accent hover:underline" href={objHref}>
                      {e.object}
                    </Link>
                  ) : (
                    e.object
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
