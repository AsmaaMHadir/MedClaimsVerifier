import Link from "next/link";

interface Props {
  title: string;
  items: string[];
  emptyHint?: string;
  href?: (name: string) => string | null;
  accent?: string;
}

export function FactList({ title, items, emptyHint, href, accent }: Props) {
  return (
    <div className="card p-5">
      <div className="mb-4 flex items-center justify-between">
        <h3 className={`eyebrow font-semibold ${accent ?? ""}`}>{title}</h3>
        <span className="text-[11px] tabular-nums text-ink-dim">
          {items.length}
        </span>
      </div>
      {items.length === 0 ? (
        <p className="text-sm text-ink-dim">{emptyHint ?? "Nothing on record."}</p>
      ) : (
        <ul className="flex flex-wrap gap-1.5">
          {items.map((it) => {
            const link = href?.(it) ?? null;
            const chip = (
              <span className="chip border border-rule bg-bg-elevated text-ink hover:border-rule-strong">
                {it}
              </span>
            );
            return (
              <li key={it}>{link ? <Link href={link}>{chip}</Link> : chip}</li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
