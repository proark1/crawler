import { NextResponse } from "next/server";
import { api } from "@/lib/api";

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const job = await api.createJob(body);
    return NextResponse.json(job, { status: 202 });
  } catch (err) {
    console.error("create job failed", err);
    return NextResponse.json(
      { error: "Could not start the crawl. Please try again." },
      { status: 502 },
    );
  }
}
