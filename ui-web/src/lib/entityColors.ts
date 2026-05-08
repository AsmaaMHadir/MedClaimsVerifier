interface EntityStyle {
  label: string;
  color: string;
  bg: string;
  border: string;
  hex: string;
}

const STYLES: Record<string, EntityStyle> = {
  Drug: {
    label: "Drug",
    color: "text-entity-drug",
    bg: "bg-entity-drug/10",
    border: "border-entity-drug/30",
    hex: "#3a4ba6",
  },
  Disease: {
    label: "Condition",
    color: "text-entity-disease",
    bg: "bg-entity-disease/10",
    border: "border-entity-disease/30",
    hex: "#a3271f",
  },
  Symptom: {
    label: "Symptom",
    color: "text-entity-symptom",
    bg: "bg-entity-symptom/10",
    border: "border-entity-symptom/30",
    hex: "#0f5d54",
  },
  Phenotype: {
    label: "Symptom",
    color: "text-entity-phenotype",
    bg: "bg-entity-phenotype/10",
    border: "border-entity-phenotype/30",
    hex: "#0f5d54",
  },
  Effect: {
    label: "Side effect",
    color: "text-entity-effect",
    bg: "bg-entity-effect/10",
    border: "border-entity-effect/30",
    hex: "#7a4a8c",
  },
};

const FALLBACK: EntityStyle = {
  label: "Entity",
  color: "text-entity-medical",
  bg: "bg-entity-medical/10",
  border: "border-entity-medical/30",
  hex: "#6b6660",
};

export function styleForEntity(type: string): EntityStyle {
  return STYLES[type] ?? FALLBACK;
}

export function colorForType(type: string): string {
  return (STYLES[type] ?? FALLBACK).hex;
}
