import { NextResponse } from "next/server";
import { api } from "@/lib/api";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const result = await api.crawl(body);
    return NextResponse.json(result);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return new NextResponse(msg, { status: 500 });
  }
}
