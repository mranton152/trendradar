import { NextResponse } from "next/server";

const apiUrl = process.env.API_URL ?? "http://localhost:8000";

export async function GET(_: Request, { params }: { params: Promise<{ jobId: string }> }) {
  const { jobId } = await params;
  const response = await fetch(`${apiUrl}/api/v1/live/${encodeURIComponent(jobId)}`);
  return NextResponse.json(await response.json(), { status: response.status });
}
