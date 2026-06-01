import { api } from "@/lib/api";

// Proxies the backend Server-Sent Events stream, injecting the API key
// server-side so the browser's EventSource never sees the secret.
export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  try {
    const upstream = await api.streamJob(id);
    return new Response(upstream.body, {
      headers: {
        "Content-Type": "text/event-stream",
        "Cache-Control": "no-cache, no-transform",
        Connection: "keep-alive",
      },
    });
  } catch {
    return new Response('event: error\ndata: {"error":"unavailable"}\n\n', {
      status: 200,
      headers: { "Content-Type": "text/event-stream" },
    });
  }
}
