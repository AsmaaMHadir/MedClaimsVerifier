import Link from "next/link";
import { EXAMPLE_CLAIMS } from "@/lib/examples";
import { STATUS_STYLES } from "@/lib/statusStyles";

export function ExampleClaimGrid() {
  return (
    <div className="grid gap-px bg-rule sm:grid-cols-2 lg:grid-cols-3">
      {EXAMPLE_CLAIMS.map((ex) => {
        const s = STATUS_STYLES[ex.expected];
        const href = `/verify?claim=${encodeURIComponent(ex.claim)}&auto=1`;
        return (
          <Link
            key={ex.id}
            href={href}
            className="group flex flex-col gap-3 bg-bg-elevated p-5 transition-colors hover:bg-bg-subtle"
          >
            <div className="flex items-center justify-between">
              <span className={`pill border ${s.border} ${s.bg} ${s.color}`}>
                <span className="h-1.5 w-1.5 rounded-full bg-current" />
                {s.label}
              </span>
              <span className="text-[11px] uppercase tracking-wider text-ink-dim">
                {ex.label}
              </span>
            </div>
            <p className="font-serif text-base leading-snug text-ink">
              “{ex.claim}”
            </p>
            <p className="mt-auto text-xs text-ink-muted">{ex.hint}</p>
            <span className="text-xs text-accent opacity-0 transition-opacity group-hover:opacity-100">
              Check it →
            </span>
          </Link>
        );
      })}
    </div>
  );
}
