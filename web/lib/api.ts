import "server-only";

function normalizeBase(raw: string): string {
  const trimmed = raw.trim().replace(/\/+$/, "");
  if (!trimmed) return "http://localhost:8000";
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return `https://${trimmed}`;
}

const BASE = normalizeBase(process.env.CRAWLER_API_URL ?? "http://localhost:8000");
const KEY = process.env.CRAWLER_API_KEY ?? "";

export type Page = {
  id: number | null;
  url: string;
  final_url: string | null;
  status: number | null;
  title: string | null;
  text: string | null;
  links: string[];
  metadata: Record<string, unknown>;
  render_mode: string;
  error: string | null;
  fetched_at: string | null;
};

export type CrawlResponse = {
  count: number;
  pages: Page[];
};

type Init = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
  cache?: RequestCache;
};

export async function apiFetch<T>(path: string, init: Init = {}): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(init.headers ?? {}),
  };
  if (KEY) headers["X-API-Key"] = KEY;

  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers,
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
  list: (limit = 50, offset = 0) =>
    apiFetch<Page[]>(`/pages?limit=${limit}&offset=${offset}`),
  search: (q: string, limit = 50) =>
    apiFetch<Page[]>(`/pages/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  get: (id: number) => apiFetch<Page>(`/pages/${id}`),
};
