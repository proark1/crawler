export type Page = {
  id: number | null;
  url: string;
  final_url: string | null;
  status: number | null;
  title: string | null;
  text: string | null;
  markdown: string | null;
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

export type JobStatus = {
  id: number;
  status: string;
  total: number;
  error: string | null;
  params: Record<string, unknown>;
  created_at: string | null;
  updated_at: string | null;
  pages: Page[];
};

export type SseEvent =
  | { type: "snapshot"; pages: Page[]; status: string }
  | { type: "page"; page: Page; count: number }
  | { type: "done"; status: string; total: number; error?: string };
