"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";

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
  const [deleting, setDeleting] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onDelete(id: number) {
    if (!window.confirm("Delete this page from the index?")) return;
    setDeleting(id);
    setError(null);
    try {
      const res = await fetch(`/api/pages/${id}`, { method: "DELETE" });
      if (!res.ok && res.status !== 204) throw new Error("Delete failed");
      router.refresh();
    } catch {
      setError("Could not delete that page. Try again.");
    } finally {
      setDeleting(null);
    }
  }

  return (
    <div className="space-y-2">
      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700">
          {error}
        </div>
      )}
      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs font-medium text-neutral-500">
              <th className="px-5 py-3 font-medium">Name</th>
              <th className="hidden px-5 py-3 font-medium sm:table-cell">Mode</th>
              <th className="hidden px-5 py-3 font-medium md:table-cell">Fetched</th>
              <th className="px-5 py-3 font-medium">Status</th>
              <th className="px-5 py-3 font-medium text-right">Actions</th>
            </tr>
          </thead>
          <tbody>
            {pages.map((p) => (
              <tr
                key={p.id ?? p.url}
                className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50"
              >
                <td className="px-5 py-3">
                  <div className="flex items-center gap-3">
                    <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-indigo-500">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
                        <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z" />
                        <path d="M14 3v6h6" />
                      </svg>
                    </span>
                    <div className="min-w-0">
                      {p.id != null ? (
                        <Link href={`/pages/${p.id}`} className="block truncate font-medium text-neutral-900 hover:underline">
                          {p.title ?? p.url}
                        </Link>
                      ) : (
                        <span className="block truncate font-medium text-neutral-900">
                          {p.title ?? p.url}
                        </span>
                      )}
                      <span className="block truncate text-xs text-neutral-500">{p.url}</span>
                    </div>
                  </div>
                </td>
                <td className="hidden px-5 py-3 sm:table-cell">
                  <span className="rounded-md bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700">
                    {p.render_mode}
                  </span>
                </td>
                <td className="hidden px-5 py-3 text-xs text-neutral-500 md:table-cell">
                  {p.fetched_at ? new Date(p.fetched_at).toLocaleString() : "—"}
                </td>
                <td className="px-5 py-3 text-neutral-600">{p.status ?? "—"}</td>
                <td className="px-5 py-3 text-right">
                  {p.id != null && (
                    <button
                      type="button"
                      onClick={() => onDelete(p.id as number)}
                      disabled={deleting === p.id}
                      aria-label="Delete page"
                      className="inline-flex items-center rounded-md p-1.5 text-neutral-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-40"
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
          <div className="px-5 py-12 text-center text-sm text-neutral-500">
            Nothing here yet. Start a new crawl to populate this list.
          </div>
        )}
      </div>
    </div>
  );
}
