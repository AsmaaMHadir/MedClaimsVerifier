import type { VerificationStatus } from "@/types/medverify";

interface StatusStyle {
  label: string;
  color: string;
  bg: string;
  border: string;
  description: string;
}

export const STATUS_STYLES: Record<VerificationStatus, StatusStyle> = {
  SUPPORTED: {
    label: "Supported",
    color: "text-verdict-supported",
    bg: "bg-verdict-supported/8",
    border: "border-verdict-supported/40",
    description:
      "Clinical evidence supports this claim.",
  },
  CONTRADICTED: {
    label: "Contradicted",
    color: "text-verdict-contradicted",
    bg: "bg-verdict-contradicted/8",
    border: "border-verdict-contradicted/40",
    description:
      "Clinical evidence indicates this combination is unsafe or unsupported.",
  },
  NOT_FOUND: {
    label: "Not Found",
    color: "text-verdict-notfound",
    bg: "bg-verdict-notfound/8",
    border: "border-verdict-notfound/40",
    description:
      "The terms were recognised but no clinical evidence connects them.",
  },
  PARTIAL: {
    label: "Partial",
    color: "text-verdict-partial",
    bg: "bg-verdict-partial/8",
    border: "border-verdict-partial/40",
    description:
      "Mixed evidence. Some aspects of the claim are supported, others are not.",
  },
  UNKNOWN: {
    label: "Unknown",
    color: "text-verdict-unknown",
    bg: "bg-verdict-unknown/8",
    border: "border-verdict-unknown/40",
    description:
      "Not enough recognisable medical terms in the input to verify a claim.",
  },
};

export function statusOf(s: string): VerificationStatus {
  if (
    s === "SUPPORTED" ||
    s === "CONTRADICTED" ||
    s === "NOT_FOUND" ||
    s === "PARTIAL" ||
    s === "UNKNOWN"
  )
    return s;
  return "UNKNOWN";
}
