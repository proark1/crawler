import Link from "next/link";
import { api, type Page } from "@/lib/api";
import Time from "../components/time";

const PAGE_SIZE = 50;

type SearchParams = Promise<{ q?: string; page?: string }>;

export default async function PagesIndex({ searchParams }: { searchParams: SearchParams }) {
  const sp = await searchParams;
  const q = sp.q;
  const pageNum = Math.max(1, Number(sp.page) || 1);
  const offset = (pageNum - 1) * PAGE_SIZE;

  // Search isn't paginated server-side; list view is, via limit/offset.
  const pages: Page[] = q ? await api.search(q, 100) : await api.list(PAGE_SIZE, offset);
  const hasNext = !q && pages.length === PAGE_SIZE;
  const hasPrev = !q && pageNum > 1;

  const pageHref = (n: number) =>
    `/pages?${new URLSearchParams({ ...(q ? { q } : {}), page: String(n) })}`;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Pages</h1>
        <p className="mt-1 text-sm text-neutral-600 dark:text-neutral-400">
          {pages.length} result{pages.length === 1 ? "" : "s"}
          {q ? ` for "${q}"` : ` · page ${pageNum}`}
        </p>
      </div>

      <form className="flex gap-2">
        <input
          type="search"
          name="q"
          defaultValue={q ?? ""}
          placeholder="Search title, text, URL…"
          aria-label="Search crawled pages"
          className="flex-1 rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm"
        />
        <button
          type="submit"
          className="rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-4 py-2 text-sm font-medium"
        >
          Search
        </button>
      </form>

      <ul className="space-y-2">
        {pages.map((p) => (
          <li
            key={p.id ?? p.url}
            className="rounded-md border border-neutral-200 dark:border-neutral-800 px-4 py-3"
          >
            <div className="flex items-center gap-2 text-xs text-neutral-500">
              <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-1.5 py-0.5 font-mono">
                {p.render_mode}
              </span>
              {p.status && <span>{p.status}</span>}
              {p.fetched_at && <Time iso={p.fetched_at} />}
            </div>
            {p.id != null ? (
              <Link href={`/pages/${p.id}`} className="block">
                <div className="mt-1 font-medium truncate hover:underline">
                  {p.title ?? p.url}
                </div>
                <div className="text-xs text-neutral-500 truncate">{p.url}</div>
              </Link>
            ) : (
              <>
                <div className="mt-1 font-medium truncate">{p.title ?? p.url}</div>
                <div className="text-xs text-neutral-500 truncate">{p.url}</div>
              </>
            )}
            {p.text && (
              <p className="mt-2 text-sm text-neutral-700 dark:text-neutral-300 line-clamp-2">
                {p.text.slice(0, 240)}
              </p>
            )}
          </li>
        ))}
      </ul>

      {pages.length === 0 && <p className="text-sm text-neutral-500">Nothing here yet.</p>}

      {(hasPrev || hasNext) && (
        <nav className="flex items-center justify-between pt-2 text-sm" aria-label="Pagination">
          {hasPrev ? (
            <Link href={pageHref(pageNum - 1)} className="text-blue-600 dark:text-blue-400 hover:underline">
              ← Previous
            </Link>
          ) : (
            <span />
          )}
          {hasNext ? (
            <Link href={pageHref(pageNum + 1)} className="text-blue-600 dark:text-blue-400 hover:underline">
              Next →
            </Link>
          ) : (
            <span />
          )}
        </nav>
      )}
    </div>
  );
}
