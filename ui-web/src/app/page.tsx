"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { ExampleClaimGrid } from "@/components/verify/ExampleClaimGrid";

export default function HomePage() {
  const router = useRouter();
  const [text, setText] = useState("");

  const submit = () => {
    if (!text.trim()) return;
    router.push(`/verify?claim=${encodeURIComponent(text.trim())}&auto=1`);
  };

  return (
    <div className="flex flex-col gap-20">
      {/* Hero: single confident action */}
      <section className="pt-6">
        <p className="eyebrow">Medical claim verification</p>
        <h1 className="mt-3 max-w-3xl font-serif text-5xl leading-[1.05] tracking-tighter2 text-ink sm:text-6xl">
          Check medical claims for{" "}
          <span className="text-accent">clinical accuracy</span>.
        </h1>
        <p className="mt-5 max-w-xl text-lg leading-relaxed text-ink-muted">
          Paste any medical statement about a drug, a condition, a side
          effect, or a treatment, and get a clear verdict with the supporting
          evidence behind it.
        </p>

        <form
          onSubmit={(e) => {
            e.preventDefault();
            submit();
          }}
          className="mt-10 flex max-w-2xl flex-col gap-3 sm:flex-row"
        >
          <input
            className="input flex-1"
            placeholder="e.g. Metformin treats Type 2 Diabetes"
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoFocus
          />
          <button type="submit" className="btn-primary px-6">
            Check claim
          </button>
        </form>
        <p className="mt-3 text-xs text-ink-dim">
          Or pick an example below.
        </p>
      </section>

      {/* What it does: three plain statements */}
      <section>
        <p className="eyebrow">What you get back</p>
        <div className="mt-6 grid gap-px bg-rule sm:grid-cols-3">
          {[
            {
              title: "A clear verdict",
              body: "Supported, contradicted, or unverifiable, with a confidence score you can act on.",
            },
            {
              title: "The evidence",
              body: "Every verdict is traceable to specific clinical relationships behind it.",
            },
            {
              title: "The full picture",
              body: "Explore the connected medical context: related drugs, conditions, and effects.",
            },
          ].map((f) => (
            <div key={f.title} className="bg-bg-elevated p-6">
              <h3 className="font-serif text-xl text-ink">{f.title}</h3>
              <p className="mt-2 text-sm leading-relaxed text-ink-muted">
                {f.body}
              </p>
            </div>
          ))}
        </div>
      </section>

      {/* Examples */}
      <section>
        <div className="flex items-baseline justify-between">
          <p className="eyebrow">Try an example</p>
          <Link
            href="/explorer"
            className="text-sm text-ink-muted hover:text-accent"
          >
            Or browse the medical knowledge base →
          </Link>
        </div>
        <div className="mt-6">
          <ExampleClaimGrid />
        </div>
      </section>
    </div>
  );
}
