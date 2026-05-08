"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const NAV = [
  { href: "/verify", label: "Verify" },
  { href: "/extract", label: "Extract" },
  { href: "/explorer", label: "Explore" },
];

export function Topbar() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-30 border-b border-rule bg-bg/80 backdrop-blur-md">
      <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
        <Link href="/" className="flex items-center gap-2.5">
          <span
            aria-hidden
            className="grid h-7 w-7 place-items-center rounded-md bg-accent text-white"
          >
            <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
              <path d="M5 12h4l2-6 4 12 2-6h2" />
            </svg>
          </span>
          <span className="font-serif text-lg font-semibold tracking-tightish text-ink">
            MedVerify
          </span>
        </Link>

        <nav className="flex items-center gap-1">
          {NAV.map((item) => {
            const active =
              pathname === item.href || pathname.startsWith(`${item.href}/`);
            return (
              <Link
                key={item.href}
                href={item.href}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  active
                    ? "text-ink bg-bg-subtle"
                    : "text-ink-muted hover:text-ink hover:bg-bg-subtle"
                }`}
              >
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
