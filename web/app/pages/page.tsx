import Link from "next/link";
import { api, type Page } from "@/lib/api";
import PagesTable, { type Row } from "./pages-table";

type SearchParams = Promise<{ q?: string; page?: string }>;

const PAGE_SIZE = 50;

export default async function PagesIndex({
  searchParams,
}: {
  searchParams: SearchParams;
}) {
  const { q, page } = await searchParams;
  const pageNum = Math.max(1, Number(page) || 1);
  const offset = (pageNum - 1) * PAGE_SIZE;

  let pages: Page[];
  let total: number;
  if (q) {
    pages = await api.search(q, 100);
    total = pages.length;
  } else {
    const res = await api.list(PAGE_SIZE, offset);
    pages = res.pages;
    total = res.total;
  }

  const totalPages = q ? 1 : Math.max(1, Math.ceil(total / PAGE_SIZE));
  const rows: Row[] = pages.map((p) => ({
    id: p.id,
    url: p.url,
    title: p.title,
    status: p.status,
    render_mode: p.render_mode,
    fetched_at: p.fetched_at,
  }));

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-[22px] font-semibold tracking-tight text-neutral-900 dark:text-neutral-100">
            Pages
          </h1>
          <p className="mt-1 text-sm text-neutral-500 dark:text-neutral-400">
            {q ? `${total} result${total === 1 ? "" : "s"} for "${q}"` : `${total} stored`}
          </p>
        </div>

        <div className="flex items-center gap-2">
          <ExportMenu />
          <Link
            href="/"
            className="inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
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
            className="h-10 w-full rounded-lg border border-neutral-200 bg-white pl-9 pr-3 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-neutral-300 focus:outline-none focus:ring-2 focus:ring-neutral-200 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100"
          />
        </label>
        <button
          type="submit"
          className="rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white shadow-sm hover:opacity-90 dark:bg-indigo-600"
        >
          Search
        </button>
        {q && (
          <Link
            href="/pages"
            className="inline-flex items-center rounded-lg border border-neutral-200 bg-white px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
          >
            Clear search
          </Link>
        )}
      </form>

      {q && (
        <p className="text-xs text-neutral-400 dark:text-neutral-500">
          Showing up to {total} matching {total === 1 ? "page" : "pages"} for “{q}”. Search results
          are not paginated — refine your query to narrow them down.
        </p>
      )}

      <PagesTable pages={rows} />

      {!q && totalPages > 1 && (
        <div className="flex items-center justify-between text-sm">
          <span className="text-neutral-500 dark:text-neutral-400">
            Page {pageNum} of {totalPages}
          </span>
          <div className="flex gap-2">
            <PageLink page={pageNum - 1} disabled={pageNum <= 1} label="Previous" />
            <PageLink page={pageNum + 1} disabled={pageNum >= totalPages} label="Next" />
          </div>
        </div>
      )}
    </div>
  );
}

function ExportMenu() {
  const base =
    "inline-flex items-center gap-1.5 rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800";
  return (
    <div className="flex items-center gap-1">
      <a href="/api/pages/export?format=json" className={base}>
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round" className="h-4 w-4">
          <path d="M12 3v12m0 0l-4-4m4 4l4-4M5 21h14" />
        </svg>
        JSON
      </a>
      <a href="/api/pages/export?format=csv" className={base}>CSV</a>
      <a href="/api/pages/export?format=md" className={base}>MD</a>
    </div>
  );
}

function PageLink({
  page,
  disabled,
  label,
}: {
  page: number;
  disabled: boolean;
  label: string;
}) {
  if (disabled) {
    return (
      <span className="cursor-not-allowed rounded-lg border border-neutral-200 bg-neutral-50 px-3 py-1.5 text-neutral-300 dark:border-neutral-800 dark:bg-neutral-800 dark:text-neutral-600">
        {label}
      </span>
    );
  }
  return (
    <Link
      href={`/pages?page=${page}`}
      className="rounded-lg border border-neutral-200 bg-white px-3 py-1.5 text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
    >
      {label}
    </Link>
  );
}
