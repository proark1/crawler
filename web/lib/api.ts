import "server-only";

function normalizeBase(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) return "http://localhost:8000";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

import type { CrawlResponse, JobStatus, Page } from "./types";

export type { CrawlResponse, JobStatus, Page } from "./types";

const BASE = normalizeBase(process.env.CRAWLER_API_URL ?? "http://localhost:8000");
const KEY = process.env.CRAWLER_API_KEY ?? "";

/** Server-side only: base URL + auth headers for proxy routes (keeps the key off the client). */
export function backendTarget(path: string): { url: string; headers: Record<string, string> } {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (KEY) headers["X-API-Key"] = KEY;
  return { url: `${BASE}${path}`, headers };
}

type Init = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
  cache?: RequestCache;
};

export async function apiFetch<T>(path: string, init: Init = {}): Promise<T> {
  const { url, headers } = backendTarget(path);
  const res = await fetch(url, {
    ...init,
    headers: { ...headers, ...(init.headers ?? {}) },
    cache: init.cache ?? "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new Error(`API ${res.status}: ${body || res.statusText}`);
  }
  return res.json() as Promise<T>;
}

export const api = {
  crawl: (body: Record<string, unknown>) =>
    apiFetch<CrawlResponse>("/crawl", { method: "POST", body: JSON.stringify(body) }),
  startJob: (body: Record<string, unknown>) =>
    apiFetch<{ job_id: number }>("/jobs", { method: "POST", body: JSON.stringify(body) }),
  job: (id: number) => apiFetch<JobStatus>(`/jobs/${id}`),
  list: (limit = 50, offset = 0) => apiFetch<Page[]>(`/pages?limit=${limit}&offset=${offset}`),
  search: (q: string, limit = 50) =>
    apiFetch<Page[]>(`/pages/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  get: (id: number) => apiFetch<Page>(`/pages/${id}`),
};
