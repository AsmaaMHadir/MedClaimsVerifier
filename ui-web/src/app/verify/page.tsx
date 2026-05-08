import { Suspense } from "react";
import { VerifyClient } from "./VerifyClient";

export default function VerifyPage() {
  return (
    <Suspense fallback={<div className="text-ink-muted">Loading…</div>}>
      <VerifyClient />
    </Suspense>
  );
}
