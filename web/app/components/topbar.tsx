"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export default function Topbar() {
  const router = useRouter();
  const [q, setQ] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) return;
    router.push(`/pages?q=${encodeURIComponent(trimmed)}`);
  }

  return (
    <header className="sticky top-0 z-10 border-b border-neutral-200 bg-[rgb(var(--bg))]/80 backdrop-blur">
      <div className="flex h-14 items-center gap-4 px-8">
        <form onSubmit={onSubmit} className="flex flex-1 justify-center">
          <label className="relative w-full max-w-xl">
            <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400">
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                <circle cx="11" cy="11" r="7" />
                <path d="m20 20-3.5-3.5" />
              </svg>
            </span>
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              type="search"
              placeholder="Search pages"
              className="h-9 w-full rounded-lg border border-neutral-200 bg-white pl-9 pr-14 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-neutral-300 focus:outline-none focus:ring-2 focus:ring-neutral-200"
            />
            <kbd className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 rounded border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-[10px] font-medium text-neutral-500">
              ⌘K
            </kbd>
          </label>
        </form>

        <button
          type="button"
          className="flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-sm text-neutral-700 hover:bg-neutral-50"
        >
          <span className="flex h-6 w-6 items-center justify-center rounded-full bg-neutral-900 text-[11px] font-semibold text-white">
            CR
          </span>
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4 text-neutral-400">
            <path d="m6 9 6 6 6-6" />
          </svg>
        </button>
      </div>
    </header>
  );
}
