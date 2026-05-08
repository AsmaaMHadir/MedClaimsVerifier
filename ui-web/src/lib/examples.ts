import type { VerificationStatus } from "@/types/medverify";

export interface ExampleClaim {
  id: string;
  label: string;
  claim: string;
  expected: VerificationStatus;
  hint: string;
}

export const EXAMPLE_CLAIMS: ExampleClaim[] = [
  {
    id: "supported-treats",
    label: "Standard treatment",
    claim: "Metformin treats Type 2 Diabetes",
    expected: "SUPPORTED",
    hint: "A first-line therapy backed by clinical evidence.",
  },
  {
    id: "supported-warfarin",
    label: "Anticoagulant therapy",
    claim: "Warfarin treats thrombotic disease",
    expected: "SUPPORTED",
    hint: "Multiple sources support this indication.",
  },
  {
    id: "contraindicated",
    label: "Unsafe combination",
    claim: "Metformin is contraindicated in chronic kidney disease",
    expected: "CONTRADICTED",
    hint: "A documented contraindication.",
  },
  {
    id: "partial",
    label: "Mixed signal",
    claim: "Acetaminophen treats diabetes",
    expected: "PARTIAL",
    hint: "Both terms are recognised but the relationship is uncertain.",
  },
  {
    id: "not-found",
    label: "No supporting evidence",
    claim: "Aspirin treats peptic ulcer disease",
    expected: "NOT_FOUND",
    hint: "Recognised terms with no supporting relationship on record.",
  },
  {
    id: "unknown",
    label: "Unrecognised",
    claim: "XYZdrug treats ABCdisease",
    expected: "UNKNOWN",
    hint: "Without recognisable terms there is nothing to verify.",
  },
];
