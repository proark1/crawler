"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import Time from "../components/time";
import { useToast } from "../components/toast";

export type Row = {
  id: number | null;
  url: string;
  title: string | null;
  status: number | null;
  render_mode: string;
  fetched_at: string | null;
};

export default function PagesTable({ pages }: { pages: Row[] }) {
  const router = useRouter();
  const { notify } = useToast();
  const [busy, setBusy] = useState(false);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  const selectableIds = pages.map((p) => p.id).filter((x): x is number => x != null);
  const allSelected = selectableIds.length > 0 && selectableIds.every((id) => selected.has(id));

  function toggle(id: number) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    setSelected(allSelected ? new Set() : new Set(selectableIds));
  }

  async function deleteIds(ids: number[]) {
    setBusy(true);
    try {
      const results = await Promise.allSettled(
        ids.map((id) => fetch(`/api/pages/${id}`, { method: "DELETE" })),
      );
      const failed = results.filter(
        (r) =>
          r.status === "rejected" ||
          (r.status === "fulfilled" && !r.value.ok && r.value.status !== 204),
      ).length;
      if (failed) notify(`${failed} page(s) could not be deleted`, "error");
      else notify(`Deleted ${ids.length} page${ids.length === 1 ? "" : "s"}`, "success");
      setSelected(new Set());
      router.refresh();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="space-y-2">
      {selected.size > 0 && (
        <div className="flex items-center justify-between rounded-lg border border-neutral-200 bg-neutral-50 px-4 py-2 text-sm dark:border-neutral-800 dark:bg-neutral-800/50">
          <span className="text-neutral-600 dark:text-neutral-300">{selected.size} selected</span>
          <button
            type="button"
            disabled={busy}
            onClick={() => {
              if (window.confirm(`Delete ${selected.size} page(s)?`)) deleteIds([...selected]);
            }}
            className="inline-flex items-center gap-1.5 rounded-md border border-red-200 bg-white px-2.5 py-1 font-medium text-red-600 hover:bg-red-50 disabled:opacity-50 dark:border-red-900 dark:bg-neutral-900 dark:hover:bg-red-950"
          >
            Delete selected
          </button>
        </div>
      )}

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs font-medium text-neutral-500 dark:border-neutral-800">
              <th className="w-10 px-5 py-3">
                <input
                  type="checkbox"
                  checked={allSelected}
                  onChange={toggleAll}
                  aria-label="Select all"
                  className="h-4 w-4 rounded border-neutral-300"
                />
              </th>
              <th className="px-5 py-3 font-medium">Name</th>
              <th className="hidden px-5 py-3 font-medium sm:table-cell">Mode</th>
              <th className="hidden px-5 py-3 font-medium md:table-cell">Fetched</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 text-right font-medium">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <tr
                key={p.id ?? p.url}
                className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-800/50"
              >
                <td className="px-5 py-3">
                  {p.id != null && (
                    <input
                      type="checkbox"
                      checked={selected.has(p.id)}
                      onChange={() => toggle(p.id as number)}
                      aria-label="Select page"
                      className="h-4 w-4 rounded border-neutral-300"
                    />
                  )}
                </td>
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-indigo-500 dark:bg-indigo-950 dark:text-indigo-400">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                        <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                        <path d="M14 3v6h6" />
                      </svg>
                    </span>
                    <div className="min-w-0">
                      {p.id != null ? (
                        <Link href={`/pages/${p.id}`} className="block truncate font-medium text-neutral-900 hover:underline dark:text-neutral-100">
                          {p.title ?? p.url}
                        </Link>
                      ) : (
                        <span className="block truncate font-medium text-neutral-900 dark:text-neutral-100">
                          {p.title ?? p.url}
                        </span>
                      )}
                      <span className="block truncate text-xs text-neutral-500 dark:text-neutral-400">{p.url}</span>
                    </div>
                  </div>
                </td>
                <td className="hidden px-5 py-3 sm:table-cell">
                  <span className="rounded-md bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                    {p.render_mode}
                  </span>
                </td>
                <td className="hidden px-5 py-3 text-xs text-neutral-500 md:table-cell dark:text-neutral-400">
                  <Time iso={p.fetched_at} />
                </td>
                <td className="px-5 py-3 text-neutral-600 dark:text-neutral-400">{p.status ?? "—"}</td>
                <td className="px-5 py-3 text-right">
                  {p.id != null && (
                    <button
                      type="button"
                      onClick={() => {
                        if (window.confirm("Delete this page?")) deleteIds([p.id as number]);
                      }}
                      disabled={busy}
                      aria-label="Delete page"
                      className="inline-flex items-center rounded-md p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40 dark:hover:bg-red-950"
                    >
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                        <path d="M3 6h18M8 6V4a1 1 0 0 1 1-1h6a1 1 0 0 1 1 1v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6" />
                      </svg>
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {pages.length === 0 && (
          <div className="flex flex-col items-center gap-4 px-5 py-12 text-center text-sm text-neutral-500 dark:text-neutral-400">
            <span>Nothing here yet. Start a new crawl to populate this list.</span>
            <Link
              href="/"
              className="inline-flex items-center gap-1.5 rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 dark:bg-indigo-600"
            >
              <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                <path d="M12 5v14M5 12h14" />
              </svg>
              New crawl
            </Link>
          </div>
        )}
      </div>
    </div>
  );
}
