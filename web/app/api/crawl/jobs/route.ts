import { NextResponse } from "next/server";
import { api, describeApiError } from "@/lib/api";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const job = await api.createJob(body);
    return NextResponse.json(job, { status: 202 });
  } catch (err) {
    const { message, status } = describeApiError(err, "Could not start the crawl. Please try again.");
    return NextResponse.json({ error: message }, { status });
  }
}
