import { NextResponse } from "next/server";
import { api, describeApiError } from "@/lib/api";

export async function GET(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const job = await api.getJob(id);
    return NextResponse.json(job);
  } catch (err) {
    const { message, status } = describeApiError(err, "Job not found.");
    return NextResponse.json({ error: message }, { status });
  }
}

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    await api.cancelJob(id);
    return new NextResponse(null, { status: 202 });
  } catch (err) {
    const { message, status } = describeApiError(err, "Could not cancel the job.");
    return NextResponse.json({ error: message }, { status });
  }
}
