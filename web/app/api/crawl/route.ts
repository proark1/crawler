import { NextResponse } from "next/server";
import { api, describeApiError } from "@/lib/api";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const result = await api.crawl(body);
    return NextResponse.json(result);
  } catch (err) {
    const { message, status } = describeApiError(err, "Crawl failed. Check the URL and try again.");
    return NextResponse.json({ error: message }, { status });
  }
}
