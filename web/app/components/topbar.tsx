"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useCommandPalette } from "./command-palette";
import MobileNav from "./mobile-nav";
import { ThemeToggle } from "./theme";

export default function Topbar() {
  const router = useRouter();
  const { open } = useCommandPalette();
  const [q, setQ] = useState("");

  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = q.trim();
    if (!trimmed) return;
    router.push(`/pages?q=${encodeURIComponent(trimmed)}`);
  }

  return (
    <header className="sticky top-0 z-10 border-b border-neutral-200 bg-[rgb(var(--bg))]/80 backdrop-blur dark:border-neutral-800">
      <div className="flex h-14 items-center gap-3 px-4 sm:px-8">
        <MobileNav />

        <form onSubmit={onSubmit} className="flex flex-1 justify-center">
          <button
            type="button"
            onClick={open}
            aria-label="Search or jump to"
            aria-keyshortcuts="Meta+K Control+K"
            className="relative flex w-full max-w-xl items-center rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-left text-sm text-neutral-400 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:hover:bg-neutral-800"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="mr-2 h-4 w-4">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
            Search or jump to…
            <kbd className="ml-auto rounded border border-neutral-200 bg-neutral-50 px-1.5 py-0.5 text-[10px] font-medium text-neutral-500 dark:border-neutral-700 dark:bg-neutral-800">
              ⌘K
            </kbd>
          </button>
        </form>

        <ThemeToggle />
      </div>
    </header>
  );
}
