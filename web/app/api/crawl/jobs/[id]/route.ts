import { NextResponse } from "next/server";
import { api } from "@/lib/api";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const job = await api.getJob(id);
    return NextResponse.json(job);
  } catch (err) {
    console.error("poll job failed", err);
    return NextResponse.json({ error: "Job not found." }, { status: 404 });
  }
}
