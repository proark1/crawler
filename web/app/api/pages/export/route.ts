import { api } from "@/lib/api";

const TYPES: Record<string, { ct: string; ext: string }> = {
  json: { ct: "application/json", ext: "json" },
  csv: { ct: "text/csv", ext: "csv" },
  md: { ct: "text/markdown", ext: "md" },
};

export async function GET(req: Request) {
  const url = new URL(req.url);
  const format = (url.searchParams.get("format") ?? "json") as "json" | "csv" | "md";
  const meta = TYPES[format] ?? TYPES.json;
  try {
    const upstream = await api.exportStream(format);
    return new Response(upstream.body, {
      headers: {
        "Content-Type": meta.ct,
        "Content-Disposition": `attachment; filename=pages.${meta.ext}`,
      },
    });
  } catch {
    return new Response("Export failed", { status: 502 });
  }
}
