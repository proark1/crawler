import Link from "next/link";
import { api, type Page } from "@/lib/api";

type SearchParams = Promise<{ q?: string }>;

export default async function PagesIndex({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { q } = await searchParams;
  const pages: Page[] = q ? await api.search(q, 100) : await api.list(100);

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-neutral-900">
            Pages
          </h1>
          <p className="mt-1 text-sm text-neutral-500">
            {pages.length} result{pages.length === 1 ? "" : "s"}
            {q ? ` for "${q}"` : ""}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50"
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <path d="M12 5v14M5 12h14" />
            </svg>
            New crawl
          </Link>
        </div>
      </div>

      <form className="flex gap-2">
        <label className="relative flex-1">
          <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-neutral-400">
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
              <circle cx="11" cy="11" r="7" />
              <path d="m20 20-3.5-3.5" />
            </svg>
          </span>
          <input
            type="search"
            name="q"
            defaultValue={q ?? ""}
            placeholder="Search title, text, URL…"
            className="h-10 w-full rounded-lg border border-neutral-200 bg-white pl-9 pr-3 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-neutral-300 focus:outline-none focus:ring-2 focus:ring-neutral-200"
          />
        </label>
        <button
          type="submit"
          className="rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90"
        >
          Search
        </button>
      </form>

      <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-neutral-100 text-left text-xs font-medium text-neutral-500">
              <th className="px-5 py-3 font-medium">Name</th>
              <th className="hidden px-5 py-3 font-medium sm:table-cell">Mode</th>
              <th className="hidden px-5 py-3 font-medium md:table-cell">Fetched</th>
              <th className="px-5 py-3 font-medium">Status</th>
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
                <td className="px-5 py-3 text-neutral-600">
                  {p.status ?? "—"}
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
