"use client";

import Link from "next/link";
import { useCallback, useRef, useState } from "react";
import type { Page, SseEvent } from "@/lib/types";

type Status = "idle" | "running" | "done" | "error";

function clampInt(value: number, min: number, max: number, fallback: number): number {
  if (!Number.isFinite(value)) return fallback;
  return Math.min(max, Math.max(min, Math.round(value)));
}

export default function CrawlForm() {
  const [url, setUrl] = useState("");
  const [render, setRender] = useState<"auto" | "static" | "js">("auto");
  const [followLinks, setFollowLinks] = useState(false);
  const [maxDepth, setMaxDepth] = useState(1);
  const [maxPages, setMaxPages] = useState(10);
  const [sameHostOnly, setSameHostOnly] = useState(true);

  const [status, setStatus] = useState<Status>("idle");
  const [pages, setPages] = useState<Page[]>([]);
  const [error, setError] = useState<string | null>(null);

  const esRef = useRef<EventSource | null>(null);
  const seenRef = useRef<Set<string>>(new Set());

  const finish = useCallback((next: Status, message?: string) => {
    esRef.current?.close();
    esRef.current = null;
    setStatus(next);
    if (message) setError(message);
  }, []);

  const addPage = useCallback((p: Page) => {
    const key = p.id != null ? `id:${p.id}` : `url:${p.url}`;
    if (seenRef.current.has(key)) return;
    seenRef.current.add(key);
    setPages((prev) => [...prev, p]);
  }, []);

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    esRef.current?.close();
    seenRef.current = new Set();
    setPages([]);
    setError(null);
    setStatus("running");

    try {
      const res = await fetch("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          url,
          render,
          follow_links: followLinks,
          max_depth: clampInt(maxDepth, 0, 5, 1),
          max_pages: clampInt(maxPages, 1, 100, 10),
          same_host_only: sameHostOnly,
          store: true,
        }),
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({ error: res.statusText }));
        throw new Error(body.error ?? `Request failed (${res.status})`);
      }
      const { job_id } = (await res.json()) as { job_id: number };

      const es = new EventSource(`/api/jobs/${job_id}/events`);
      esRef.current = es;
      es.onmessage = (ev) => {
        const data = JSON.parse(ev.data) as SseEvent;
        if (data.type === "snapshot") {
          data.pages.forEach(addPage);
        } else if (data.type === "page") {
          addPage(data.page);
        } else if (data.type === "done") {
          if (data.status === "failed") finish("error", data.error ?? "Crawl failed");
          else finish("done");
        }
      };
      es.onerror = () => {
        // The stream closes when the job ends; treat as completion if we have results.
        if (esRef.current) finish(seenRef.current.size > 0 ? "done" : "error",
          seenRef.current.size > 0 ? undefined : "Connection to crawler lost");
      };
    } catch (err) {
      finish("error", err instanceof Error ? err.message : String(err));
    }
  }

  function cancel() {
    finish("idle");
    setError(null);
  }

  const running = status === "running";

  return (
    <div className="space-y-6">
      <form onSubmit={onSubmit} className="space-y-4">
        <div>
          <label htmlFor="url" className="sr-only">
            URL to crawl
          </label>
          <input
            id="url"
            type="url"
            required
            placeholder="https://example.com"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
            className="w-full rounded-md border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-neutral-500"
          />
        </div>

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
              onChange={(e) => setMaxDepth(clampInt(e.target.valueAsNumber, 0, 5, 1))}
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
              onChange={(e) => setMaxPages(clampInt(e.target.valueAsNumber, 1, 100, 10))}
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

        <div className="flex items-center gap-3">
          <button
            type="submit"
            disabled={running || !url}
            aria-busy={running}
            className="rounded-md bg-neutral-900 dark:bg-neutral-100 text-white dark:text-neutral-900 px-4 py-2 text-sm font-medium disabled:opacity-50"
          >
            {running ? "Crawling…" : "Crawl"}
          </button>
          {running && (
            <button
              type="button"
              onClick={cancel}
              className="rounded-md border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm"
            >
              Cancel
            </button>
          )}
          {running && (
            <span aria-live="polite" className="text-sm text-neutral-500">
              {pages.length} page{pages.length === 1 ? "" : "s"} so far…
            </span>
          )}
        </div>
      </form>

      {error && (
        <div
          role="alert"
          className="rounded-md border border-red-300 bg-red-50 dark:bg-red-950/40 dark:border-red-800 px-3 py-2 text-sm text-red-800 dark:text-red-200"
        >
          {error}
        </div>
      )}

      {pages.length > 0 && (
        <div className="space-y-3">
          <div className="text-sm text-neutral-600 dark:text-neutral-400" aria-live="polite">
            {pages.length} page{pages.length === 1 ? "" : "s"} crawled
            {status === "done" ? " · done" : status === "running" ? " · crawling…" : ""}
          </div>
          <ul className="space-y-2">
            {pages.map((p, i) => (
              <li
                key={p.id ?? `${p.url}-${i}`}
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
