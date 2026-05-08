import type { Entity } from "@/types/medverify";
import { styleForEntity } from "@/lib/entityColors";

interface Props {
  text: string;
  entities: Entity[];
}

interface Span {
  start: number;
  end: number;
  entity: Entity;
}

export function HighlightedClaim({ text, entities }: Props) {
  const spans: Span[] = entities
    .filter(
      (e): e is Entity & { start: number; end: number } =>
        typeof e.start === "number" &&
        typeof e.end === "number" &&
        e.end > e.start
    )
    .map((e) => ({ start: e.start, end: e.end, entity: e }))
    .sort((a, b) => a.start - b.start);

  // Drop overlaps (keep first occurrence).
  const clean: Span[] = [];
  for (const s of spans) {
    const last = clean[clean.length - 1];
    if (!last || s.start >= last.end) clean.push(s);
  }

  if (clean.length === 0) {
    return (
      <p className="font-serif text-xl leading-relaxed text-ink">{text}</p>
    );
  }

  const parts: React.ReactNode[] = [];
  let cursor = 0;
  clean.forEach((sp, i) => {
    if (sp.start > cursor)
      parts.push(<span key={`t-${i}`}>{text.slice(cursor, sp.start)}</span>);
    const slice = text.slice(sp.start, sp.end);
    const style = styleForEntity(sp.entity.type);
    parts.push(
      <span
        key={`e-${i}`}
        className={`inline rounded-sm px-1 ${style.bg} ${style.color} ${
          sp.entity.negated ? "line-through opacity-70" : ""
        }`}
        title={sp.entity.type}
      >
        {slice}
      </span>
    );
    cursor = sp.end;
  });
  if (cursor < text.length)
    parts.push(<span key="t-end">{text.slice(cursor)}</span>);

  return (
    <p className="font-serif text-xl leading-relaxed text-ink">{parts}</p>
  );
}
