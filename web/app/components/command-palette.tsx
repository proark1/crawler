"use client";

import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState } from "react";

type Ctx = { open: () => void };
const PaletteContext = createContext<Ctx>({ open: () => {} });

export function useCommandPalette() {
  return useContext(PaletteContext);
}

type Action = { label: string; hint?: string; run: () => void };

export function CommandPaletteProvider({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [isOpen, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [active, setActive] = useState(0);
  const dialogRef = useRef<HTMLDivElement | null>(null);
  const previouslyFocused = useRef<HTMLElement | null>(null);

  const open = useCallback(() => {
    // Capture focus *before* opening — once open, the input's autoFocus steals
    // it, so capturing inside the effect would record the input, not the trigger.
    previouslyFocused.current = document.activeElement as HTMLElement | null;
    setOpen(true);
  }, []);
  const close = useCallback(() => {
    setOpen(false);
    setQuery("");
    setActive(0);
  }, []);

  const actions: Action[] = useMemo(() => {
    const base: Action[] = [
      { label: "New crawl", hint: "Go", run: () => router.push("/") },
      { label: "Pages", hint: "Go", run: () => router.push("/pages") },
      { label: "Jobs", hint: "Go", run: () => router.push("/jobs") },
      { label: "Domains", hint: "Go", run: () => router.push("/domains") },
      { label: "Settings", hint: "Go", run: () => router.push("/settings") },
    ];
    if (query.trim()) {
      base.unshift({
        label: `Search pages for “${query.trim()}”`,
        hint: "Enter",
        run: () => router.push(`/pages?q=${encodeURIComponent(query.trim())}`),
      });
    }
    return base;
  }, [query, router]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return actions;
    return actions.filter(
      (a) => a.label.toLowerCase().includes(q) || a.label.startsWith("Search pages"),
    );
  }, [actions, query]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        if (!isOpen) {
          // Capture the pre-open focus when opening via the shortcut too.
          previouslyFocused.current = document.activeElement as HTMLElement | null;
          setOpen(true);
        } else {
          close();
        }
      } else if (e.key === "Escape") {
        close();
      }
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [isOpen, close]);

  // Focus trap + restore focus to the trigger when the palette closes.
  // (previouslyFocused is captured at open time, before the input autofocuses.)
  useEffect(() => {
    if (!isOpen) return;

    function onKeyDown(e: KeyboardEvent) {
      if (e.key !== "Tab") return;
      const root = dialogRef.current;
      if (!root) return;
      const focusable = root.querySelectorAll<HTMLElement>(
        'a[href], button:not([disabled]), input, [tabindex]:not([tabindex="-1"])',
      );
      if (focusable.length === 0) return;
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
      }
    }

    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      previouslyFocused.current?.focus?.();
    };
  }, [isOpen]);

  function onKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setActive((a) => Math.min(a + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActive((a) => Math.max(a - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const action = filtered[active];
      if (action) {
        action.run();
        close();
      }
    }
  }

  return (
    <PaletteContext.Provider value={{ open }}>
      {children}
      {isOpen && (
        <div
          className="fixed inset-0 z-50 flex items-start justify-center bg-black/30 pt-[15vh]"
          onClick={close}
        >
          <div
            ref={dialogRef}
            role="dialog"
            aria-modal="true"
            aria-label="Command palette"
            className="w-full max-w-lg overflow-hidden rounded-xl border border-neutral-200 bg-white shadow-2xl dark:border-neutral-700 dark:bg-neutral-900"
            onClick={(e) => e.stopPropagation()}
          >
            <input
              autoFocus
              value={query}
              onChange={(e) => {
                setQuery(e.target.value);
                setActive(0);
              }}
              onKeyDown={onKeyDown}
              placeholder="Search or jump to…"
              className="w-full border-b border-neutral-100 bg-transparent px-4 py-3 text-sm text-neutral-900 placeholder:text-neutral-400 focus:outline-none dark:border-neutral-800 dark:text-neutral-100"
            />
            <ul className="max-h-72 overflow-auto py-1">
              {filtered.map((a, i) => (
                <li key={a.label}>
                  <button
                    type="button"
                    onMouseEnter={() => setActive(i)}
                    onClick={() => {
                      a.run();
                      close();
                    }}
                    className={[
                      "flex w-full items-center justify-between px-4 py-2 text-left text-sm",
                      i === active
                        ? "bg-neutral-100 text-neutral-900 dark:bg-neutral-800 dark:text-neutral-100"
                        : "text-neutral-600 dark:text-neutral-300",
                    ].join(" ")}
                  >
                    {a.label}
                    {a.hint && (
                      <span className="text-xs text-neutral-400">{a.hint}</span>
                    )}
                  </button>
                </li>
              ))}
              {filtered.length === 0 && (
                <li className="px-4 py-6 text-center text-sm text-neutral-400">
                  No matches
                </li>
              )}
            </ul>
          </div>
        </div>
      )}
    </PaletteContext.Provider>
  );
}
