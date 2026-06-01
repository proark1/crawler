import { backendTarget } from "@/lib/api";

// SSE proxy: streams the backend's job events to the browser while keeping the
// API key server-side. force-dynamic + a generous maxDuration so long crawls
// aren't cut off by the platform's default function timeout.
export const dynamic = "force-dynamic";
export const maxDuration = 300;

export async function GET(req: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const { url, headers } = backendTarget(`/jobs/${encodeURIComponent(id)}/events`);

  const upstream = await fetch(url, {
    headers: { ...headers, Accept: "text/event-stream" },
    signal: req.signal,
  });

  if (!upstream.ok || !upstream.body) {
    return new Response(`upstream error ${upstream.status}`, { status: 502 });
  }

  return new Response(upstream.body, {
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
