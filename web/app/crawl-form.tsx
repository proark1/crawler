"use client";

import Link from "next/link";
import { useEffect, useRef, useState } from "react";
import { useToast } from "./components/toast";

type Page = {
  id: number | null;
  url: string;
  final_url: string | null;
  status: number | null;
  title: string | null;
  text: string | null;
  links: string[];
  render_mode: string;
  error: string | null;
};

type Job = {
  id: string;
  status: "pending" | "running" | "done" | "error";
  progress: number;
  total: number | null;
  count: number;
  pages: Page[];
  error: string | null;
};

export default function CrawlForm() {
  const { notify } = useToast();
  const [url, setUrl] = useState("");
  const [render, setRender] = useState<"auto" | "static" | "js">("auto");
  const [followLinks, setFollowLinks] = useState(false);
  const [maxDepth, setMaxDepth] = useState(1);
  const [maxPages, setMaxPages] = useState(10);
  const [sameHostOnly, setSameHostOnly] = useState(true);
  const [useSitemap, setUseSitemap] = useState(true);

  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [pages, setPages] = useState<Page[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const cancelled = useRef(false);
  const esRef = useRef<EventSource | null>(null);

  // Tear down any live stream/polling if the user navigates away mid-crawl.
  useEffect(() => {
    return () => {
      cancelled.current = true;
      esRef.current?.close();
    };
  }, []);

  async function pollUntilDone(id: string): Promise<Job> {
    let current: Job | null = null;
    while (!current || current.status === "pending" || current.status === "running") {
      if (cancelled.current) throw new Error("cancelled");
      await new Promise((r) => setTimeout(r, 700));
      const res = await fetch(`/api/crawl/jobs/${id}`);
      if (!res.ok) throw new Error("Lost track of the crawl job");
      current = (await res.json()) as Job;
      setJob(current);
    }
    return current;
  }

  function streamUntilDone(id: string): Promise<Job> {
    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (j: Job) => {
        if (settled) return;
        settled = true;
        esRef.current?.close();
        resolve(j);
      };
      let es: EventSource;
      try {
        es = new EventSource(`/api/crawl/jobs/${id}/stream`);
      } catch {
        pollUntilDone(id).then(resolve).catch(reject);
        return;
      }
      esRef.current = es;
      es.onmessage = (e) => {
        try {
          const data = JSON.parse(e.data) as Job;
          setJob(data);
          if (data.status === "done" || data.status === "error") finish(data);
        } catch {
          /* ignore keep-alives / parse errors */
        }
      };
      es.onerror = () => {
        es.close();
        if (!settled) {
          // Fall back to polling if the stream drops before completion.
          pollUntilDone(id).then(finish).catch(reject);
        }
      };
    });
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setPages(null);
    setJob(null);
    cancelled.current = false;

    try {
      const startRes = await fetch("/api/crawl/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          render,
          follow_links: followLinks,
          max_depth: maxDepth,
          max_pages: maxPages,
          same_host_only: sameHostOnly,
          use_sitemap: useSitemap,
          store: true,
        }),
      });
      if (!startRes.ok) throw new Error((await startRes.json()).error ?? "Failed to start crawl");
      const started = (await startRes.json()) as Job;
      setJob(started);

      const final = await streamUntilDone(started.id);
      if (final.status === "error") throw new Error(final.error ?? "Crawl failed");
      setPages(final.pages);
      notify(`Crawled ${final.pages.length} page${final.pages.length === 1 ? "" : "s"}`, "success");
    } catch (err) {
      if ((err as Error).message === "cancelled") return;
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      notify(msg, "error");
    } finally {
      setLoading(false);
    }
  }

  const inputBase =
    "w-full rounded-lg border border-neutral-200 bg-white px-3 py-2 text-sm text-neutral-900 placeholder:text-neutral-400 focus:border-neutral-300 focus:outline-none focus:ring-2 focus:ring-neutral-200 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-100 dark:focus:ring-neutral-700";

  const pct =
    job && job.total && job.total > 0
      ? Math.min(100, Math.round((job.progress / job.total) * 100))
      : null;

  return (
    <div className="space-y-6">
      <form
        onSubmit={onSubmit}
        className="space-y-5 rounded-xl border border-neutral-200 bg-white p-6 shadow-[0_1px_2px_rgba(15,23,42,0.04)] dark:border-neutral-800 dark:bg-neutral-900"
      >
        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">URL</span>
          <input
            type="url"
            required
            placeholder="https://example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className={inputBase}
          />
        </label>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Render</span>
            <select
              value={render}
              onChange={(e) => setRender(e.target.value as typeof render)}
              className={inputBase}
            >
              <option value="auto">Auto · static, JS fallback</option>
              <option value="static">Static only</option>
              <option value="js">JS only</option>
            </select>
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Max depth</span>
            <input
              type="number"
              min={0}
              max={5}
              value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value))}
              disabled={!followLinks}
              className={`${inputBase} disabled:bg-neutral-50 disabled:text-neutral-400 dark:disabled:bg-neutral-800`}
            />
          </label>

          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Max pages</span>
            <input
              type="number"
              min={1}
              max={100}
              value={maxPages}
              onChange={(e) => setMaxPages(Number(e.target.value))}
              disabled={!followLinks}
              className={`${inputBase} disabled:bg-neutral-50 disabled:text-neutral-400 dark:disabled:bg-neutral-800`}
            />
          </label>
        </div>

        <div className="flex flex-wrap items-center gap-5 border-t border-neutral-100 pt-4 text-sm dark:border-neutral-800">
          <label className="inline-flex cursor-pointer items-center gap-2 text-neutral-700 dark:text-neutral-300">
            <input
              type="checkbox"
              checked={followLinks}
              onChange={(e) => setFollowLinks(e.target.checked)}
              className="h-4 w-4 rounded border-neutral-300 text-[#0B1739] focus:ring-neutral-300"
            />
            Follow links (BFS)
          </label>
          <label className="inline-flex cursor-pointer items-center gap-2 text-neutral-700 dark:text-neutral-300">
            <input
              type="checkbox"
              checked={sameHostOnly}
              onChange={(e) => setSameHostOnly(e.target.checked)}
              disabled={!followLinks}
              className="h-4 w-4 rounded border-neutral-300 text-[#0B1739] focus:ring-neutral-300 disabled:opacity-50"
            />
            Same host only
          </label>
          <label className="inline-flex cursor-pointer items-center gap-2 text-neutral-700 dark:text-neutral-300">
            <input
              type="checkbox"
              checked={useSitemap}
              onChange={(e) => setUseSitemap(e.target.checked)}
              disabled={!followLinks}
              className="h-4 w-4 rounded border-neutral-300 text-[#0B1739] focus:ring-neutral-300 disabled:opacity-50"
            />
            Use sitemap
          </label>

          <button
            type="submit"
            disabled={loading || !url}
            className="ml-auto inline-flex items-center gap-2 rounded-lg bg-[#0B1739] px-4 py-2 text-sm font-medium text-white shadow-sm transition-opacity hover:opacity-90 disabled:opacity-50 dark:bg-indigo-600"
          >
            {loading ? (
              <>
                <svg className="h-4 w-4 animate-spin" viewBox="0 0 24 24" fill="none">
                  <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity="0.25" strokeWidth="3" />
                  <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="3" strokeLinecap="round" />
                </svg>
                Crawling…
              </>
            ) : (
              "Start crawl"
            )}
          </button>
        </div>
      </form>

      {loading && job && (
        <div className="rounded-lg border border-neutral-200 bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
          <div className="mb-2 flex items-center justify-between text-xs text-neutral-600 dark:text-neutral-400">
            <span>
              {job.status === "pending" ? "Queued…" : "Crawling…"} {job.progress}
              {job.total ? ` / ${job.total}` : ""} page{job.progress === 1 ? "" : "s"}
            </span>
            {pct != null && <span>{pct}%</span>}
          </div>
          <div className="h-1.5 w-full overflow-hidden rounded-full bg-neutral-100 dark:bg-neutral-800">
            <div
              className="h-full rounded-full bg-[#0B1739] transition-all dark:bg-indigo-500"
              style={{ width: pct != null ? `${pct}%` : "40%" }}
            />
          </div>
        </div>
      )}

      {error && (
        <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900 dark:bg-red-950 dark:text-red-300">
          {error}
        </div>
      )}

      {pages && (
        <div className="space-y-3">
          <div className="text-sm text-neutral-500 dark:text-neutral-400">
            {pages.length} page{pages.length === 1 ? "" : "s"} crawled
          </div>
          <div className="overflow-hidden rounded-xl border border-neutral-200 bg-white dark:border-neutral-800 dark:bg-neutral-900">
            <ResultTable pages={pages} />
          </div>
        </div>
      )}
    </div>
  );
}

function ResultTable({ pages }: { pages: Page[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className="border-b border-neutral-100 text-left text-xs font-medium text-neutral-500 dark:border-neutral-800">
          <th className="px-5 py-3 font-medium">Name</th>
          <th className="px-5 py-3 font-medium">Mode</th>
          <th className="px-5 py-3 font-medium">Status</th>
        </tr>
      </thead>
      <tbody>
        {pages.map((p, i) => (
          <tr key={p.id ?? i} className="border-b border-neutral-100 last:border-0 hover:bg-neutral-50 dark:border-neutral-800 dark:hover:bg-neutral-800/50">
            <td className="px-5 py-3">
              <div className="flex items-center gap-3">
                <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-md bg-indigo-50 text-indigo-500 dark:bg-indigo-950 dark:text-indigo-400">
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
                    <span className="block truncate font-medium text-neutral-900 dark:text-neutral-100">{p.title ?? p.url}</span>
                  )}
                  <span className="block truncate text-xs text-neutral-500 dark:text-neutral-400">{p.url}</span>
                </div>
              </div>
            </td>
            <td className="px-5 py-3">
              <span className="rounded-md bg-neutral-100 px-2 py-0.5 font-mono text-xs text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300">
                {p.render_mode}
              </span>
            </td>
            <td className="px-5 py-3 text-neutral-600 dark:text-neutral-400">
              {p.error ? (
                <span className="text-red-600 dark:text-red-400">{p.error}</span>
              ) : (
                <span>{p.status ?? "—"}</span>
              )}
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
