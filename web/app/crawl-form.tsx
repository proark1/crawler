"use client";

import Link from "next/link";
import { useState } from "react";

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

type CrawlResponse = { count: number; pages: Page[] };

export default function CrawlForm() {
  const [url, setUrl] = useState("");
  const [render, setRender] = useState<"auto" | "static" | "js">("auto");
  const [followLinks, setFollowLinks] = useState(false);
  const [maxDepth, setMaxDepth] = useState(1);
  const [maxPages, setMaxPages] = useState(10);
  const [sameHostOnly, setSameHostOnly] = useState(true);

  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<CrawlResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const res = await fetch("/api/crawl", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          render,
          follow_links: followLinks,
          max_depth: maxDepth,
          max_pages: maxPages,
          same_host_only: sameHostOnly,
          store: true,
        }),
      });
      if (!res.ok) throw new Error(await res.text());
      setResult((await res.json()) as CrawlResponse);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-4">
        <input
          type="url"
          required
          placeholder="https://example.com"
          value={url}
          onChange={(e) => setUrl(e.target.value)}
          className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-500"
        />

        <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 text-sm">
          <label className="flex flex-col gap-1">
            <span className="text-neutral-600 dark:text-neutral-400">Render</span>
            <select
              value={render}
              onChange={(e) => setRender(e.target.value as typeof render)}
              className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1.5"
            >
              <option value="auto">auto (static, JS fallback)</option>
              <option value="static">static only</option>
              <option value="js">js only</option>
            </select>
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-neutral-600 dark:text-neutral-400">Max depth</span>
            <input
              type="number"
              min={0}
              max={5}
              value={maxDepth}
              onChange={(e) => setMaxDepth(Number(e.target.value))}
              disabled={!followLinks}
              className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1.5 disabled:opacity-50"
            />
          </label>

          <label className="flex flex-col gap-1">
            <span className="text-neutral-600 dark:text-neutral-400">Max pages</span>
            <input
              type="number"
              min={1}
              max={100}
              value={maxPages}
              onChange={(e) => setMaxPages(Number(e.target.value))}
              disabled={!followLinks}
              className="rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-2 py-1.5 disabled:opacity-50"
            />
          </label>
        </div>

        <div className="flex flex-wrap gap-4 text-sm">
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={followLinks}
              onChange={(e) => setFollowLinks(e.target.checked)}
            />
            Follow links (BFS)
          </label>
          <label className="flex items-center gap-2">
            <input
              type="checkbox"
              checked={sameHostOnly}
              onChange={(e) => setSameHostOnly(e.target.checked)}
              disabled={!followLinks}
            />
            Same host only
          </label>
        </div>

        <button
          type="submit"
          disabled={loading || !url}
          className="rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-50"
        >
          {loading ? "Crawling…" : "Crawl"}
        </button>
      </form>

      {error && (
        <pre className="whitespace-pre-wrap rounded-md border border-red-300 bg-red-50 dark:bg-red-950/40 dark:border-red-800 px-3 py-2 text-sm text-red-800 dark:text-red-200">
          {error}
        </pre>
      )}

      {result && (
        <div className="space-y-3">
          <div className="text-sm text-neutral-600 dark:text-neutral-400">
            {result.count} page{result.count === 1 ? "" : "s"} crawled
          </div>
          <ul className="space-y-2">
            {result.pages.map((p, i) => (
              <li
                key={p.id ?? i}
                className="rounded-md border border-neutral-200 dark:border-neutral-800 px-4 py-3"
              >
                <div className="flex items-center gap-2 text-xs text-neutral-500">
                  <span className="rounded bg-neutral-100 dark:bg-neutral-800 px-1.5 py-0.5 font-mono">
                    {p.render_mode}
                  </span>
                  {p.status && <span>{p.status}</span>}
                  {p.error && <span className="text-red-600">{p.error}</span>}
                </div>
                <div className="mt-1 font-medium truncate">{p.title ?? p.url}</div>
                <div className="text-xs text-neutral-500 truncate">{p.url}</div>
                {p.id != null && (
                  <Link
                    href={`/pages/${p.id}`}
                    className="mt-1 inline-block text-xs text-blue-600 dark:text-blue-400 hover:underline"
                  >
                    View page →
                  </Link>
                )}
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
