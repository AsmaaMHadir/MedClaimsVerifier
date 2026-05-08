import type { Entity } from "@/types/medverify";
import { styleForEntity } from "@/lib/entityColors";

export function EntityChip({ entity, compact = false }: { entity: Entity; compact?: boolean }) {
  const s = styleForEntity(entity.type);
  const pct = Math.round((entity.confidence ?? 0) * 100);
  const normalized =
    entity.normalized_name &&
    entity.normalized_name.toLowerCase() !== entity.text.toLowerCase()
      ? entity.normalized_name
      : null;
  const ingredients =
    (entity.normalized_ingredients ?? []).filter(
      (i) => i.toLowerCase() !== entity.text.toLowerCase()
    );

  return (
    <span
      className={`chip border ${s.border} ${s.bg} ${s.color}`}
      title={
        normalized
          ? `${entity.type} · ${entity.text} → ${normalized}` +
            (ingredients.length > 1
              ? ` (ingredients: ${ingredients.join(", ")})`
              : "") +
            (entity.normalization_source
              ? ` · resolved via ${entity.normalization_source}`
              : "")
          : `${entity.type} · ${entity.name}${entity.negated ? " · negated" : ""}`
      }
    >
      <span className="text-[10px] uppercase tracking-wider opacity-70">
        {s.label}
      </span>
      <span className={`font-semibold ${entity.negated ? "line-through opacity-60" : ""}`}>
        {entity.text}
      </span>
      {normalized && (
        <span className="text-[11px] font-normal opacity-70">
          → {ingredients.length > 1 ? ingredients.join(" + ") : normalized}
        </span>
      )}
      {!compact && (
        <span className="ml-1 inline-block h-1 w-10 overflow-hidden rounded-full bg-ink/10">
          <span
            className="block h-full rounded-full bg-current"
            style={{ width: `${pct}%` }}
          />
        </span>
      )}
    </span>
  );
}
