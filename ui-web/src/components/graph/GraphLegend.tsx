const ITEMS: { label: string; hex: string }[] = [
  { label: "Drug", hex: "#3a4ba6" },
  { label: "Condition", hex: "#a3271f" },
  { label: "Symptom", hex: "#0f5d54" },
  { label: "Side effect", hex: "#7a4a8c" },
];

export function GraphLegend() {
  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] text-ink-muted">
      {ITEMS.map((it) => (
        <span key={it.label} className="flex items-center gap-1.5">
          <span
            className="h-2 w-2 rounded-full"
            style={{ backgroundColor: it.hex }}
          />
          {it.label}
        </span>
      ))}
      <span className="text-ink-dim">· click to expand</span>
    </div>
  );
}
