import { NextResponse } from "next/server";
import { api } from "@/lib/api";

export async function DELETE(
  _req: Request,
  { params }: { params: Promise<{ id: string }> },
) {
  try {
    const { id } = await params;
    const numericId = Number(id);
    if (!Number.isFinite(numericId)) {
      return NextResponse.json({ error: "Invalid id" }, { status: 400 });
    }
    await api.remove(numericId);
    return new NextResponse(null, { status: 204 });
  } catch (err) {
    console.error("delete page failed", err);
    return NextResponse.json({ error: "Could not delete page." }, { status: 502 });
  }
}
