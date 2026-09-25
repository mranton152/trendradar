import { NextRequest, NextResponse } from "next/server";

const apiUrl = process.env.API_URL ?? "http://localhost:8000";

export async function POST(request: NextRequest) {
  const response = await fetch(`${apiUrl}/api/v1/live`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: await request.text(),
  });
  return NextResponse.json(await response.json(), { status: response.status });
}
