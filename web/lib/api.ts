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

export type JobStatus = "pending" | "running" | "done" | "error" | "cancelled";

export type Job = {
  id: string;
  status: JobStatus;
  progress: number;
  total: number | null;
  count: number;
  pages: Page[];
  error: string | null;
};

export type DomainProfile = {
  host: string;
  min_tier: number;
  engine: string;
  successes: number;
  blocks: number;
  last_vendor: string | null;
  last_block_at: number | null;
};

export type JobSummary = {
  id: string;
  status: JobStatus;
  progress: number;
  total: number | null;
  error: string | null;
  created_at: string | null;
  updated_at: string | null;
};

type Init = Omit<RequestInit, "headers"> & {
  headers?: Record<string, string>;
  cache?: RequestCache;
};

function authHeaders(extra?: Record<string, string>): Record<string, string> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(extra ?? {}),
  };
  if (KEY) headers["X-API-Key"] = KEY;
  return headers;
}

/** Error thrown by the API client. Carries the upstream HTTP status when known. */
export class ApiError extends Error {
  status: number;
  body: string;
  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

/**
 * Turn a thrown error into a concise, user-facing message + HTTP status to
 * return from a route handler. Distinguishes unreachable service, auth, and
 * validation/4xx errors. Never leaks stack traces.
 */
export function describeApiError(
  err: unknown,
  fallback = "Something went wrong talking to the crawler service.",
): { message: string; status: number } {
  if (err instanceof ApiError) {
    const { status, body } = err;
    const detail = extractDetail(body);
    if (status === 401 || status === 403) {
      return {
        message: "Not authorized to reach the crawler service. Check the API key.",
        status,
      };
    }
    if (status === 404) {
      return { message: detail || "Not found.", status };
    }
    if (status === 409) {
      return { message: detail || "Conflict — the resource is in a state that can't accept this.", status };
    }
    if (status >= 400 && status < 500) {
      return { message: detail || "The request was rejected. Check the inputs and try again.", status };
    }
    return { message: detail || fallback, status: status >= 500 ? 502 : status };
  }
  // Network-level failure: fetch rejected before we got a response.
  return { message: "Couldn't reach the crawler service. Is it running?", status: 502 };
}

/** Pull a human-readable message out of a FastAPI error body, if present. */
function extractDetail(body: string): string {
  if (!body) return "";
  try {
    const parsed = JSON.parse(body);
    const detail = parsed?.detail ?? parsed?.error ?? parsed?.message;
    if (typeof detail === "string") return detail;
    if (Array.isArray(detail) && detail[0]?.msg) return String(detail[0].msg);
  } catch {
    // Not JSON — fall back to the raw text if it's short enough to be useful.
    if (body.length <= 200) return body;
  }
  return "";
}

async function rawFetch(path: string, init: Init = {}): Promise<Response> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: authHeaders(init.headers),
    cache: init.cache ?? "no-store",
  });
  if (!res.ok) {
    const body = await res.text();
    throw new ApiError(res.status, body || res.statusText);
  }
  return res;
}

export async function apiFetch<T>(path: string, init: Init = {}): Promise<T> {
  const res = await rawFetch(path, init);
  return res.json() as Promise<T>;
}

export const api = {
  crawl: (body: Record<string, unknown>) =>
    apiFetch<CrawlResponse>("/crawl", { method: "POST", body: JSON.stringify(body) }),
  createJob: (body: Record<string, unknown>) =>
    apiFetch<Job>("/crawl/jobs", { method: "POST", body: JSON.stringify(body) }),
  getJob: (id: string) => apiFetch<Job>(`/crawl/jobs/${encodeURIComponent(id)}`),
  cancelJob: (id: string) =>
    rawFetch(`/crawl/jobs/${encodeURIComponent(id)}`, { method: "DELETE" }).then(() => undefined),
  listJobs: (limit = 50, offset = 0) =>
    apiFetch<JobSummary[]>(`/crawl/jobs?limit=${limit}&offset=${offset}`),
  domains: (limit = 200) => apiFetch<DomainProfile[]>(`/domains?limit=${limit}`),
  streamJob: (id: string) => rawFetch(`/crawl/jobs/${encodeURIComponent(id)}/stream`),
  list: async (limit = 50, offset = 0): Promise<{ pages: Page[]; total: number }> => {
    const res = await rawFetch(`/pages?limit=${limit}&offset=${offset}`);
    const total = Number(res.headers.get("X-Total-Count") ?? "0");
    const pages = (await res.json()) as Page[];
    return { pages, total };
  },
  search: (q: string, limit = 50) =>
    apiFetch<Page[]>(`/pages/search?q=${encodeURIComponent(q)}&limit=${limit}`),
  get: (id: number) => apiFetch<Page>(`/pages/${id}`),
  remove: (id: number) =>
    rawFetch(`/pages/${id}`, { method: "DELETE" }).then(() => undefined),
  exportStream: (format: "json" | "csv" | "md") =>
    rawFetch(`/pages/export?format=${format}`),
  stats: () => apiFetch<{ total: number; errors: number; blocked: number }>(`/stats`),
};
