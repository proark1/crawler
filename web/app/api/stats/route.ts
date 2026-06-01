import { NextResponse } from "next/server";
import { api } from "@/lib/api";

export async function GET() {
  try {
    const stats = await api.stats();
    return NextResponse.json(stats);
  } catch {
    // Stats are non-critical; degrade gracefully so the sidebar still renders.
    return NextResponse.json({ total: null }, { status: 200 });
  }
}
