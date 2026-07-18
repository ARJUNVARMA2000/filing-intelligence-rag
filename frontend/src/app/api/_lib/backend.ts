import { GoogleAuth } from "google-auth-library";
import { NextResponse } from "next/server";

const API_BASE = (process.env.FIN_RAG_API_BASE ?? "http://127.0.0.1:8000").replace(/\/$/, "");
const AUTH_MODE = process.env.FIN_RAG_AUTH_MODE ?? "local";

export class BackendRequestError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly requestId?: string,
  ) {
    super(message);
  }
}

async function authHeaders(): Promise<Record<string, string>> {
  if (AUTH_MODE !== "google") return {};
  const client = await new GoogleAuth().getIdTokenClient(API_BASE);
  const headers = await client.getRequestHeaders();
  return Object.fromEntries(headers.entries());
}

export async function backendFetch(
  path: string,
  init: RequestInit = {},
  timeoutMs = 95_000,
): Promise<Response> {
  const headers = new Headers(init.headers);
  for (const [name, value] of Object.entries(await authHeaders())) headers.set(name, value);
  if (init.body) headers.set("Content-Type", "application/json");

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers,
      cache: "no-store",
      signal: AbortSignal.timeout(timeoutMs),
    });
  } catch (error) {
    const timedOut = error instanceof Error && error.name === "TimeoutError";
    throw new BackendRequestError(
      timedOut
        ? "The research request timed out. Try a narrower question."
        : "The research service is currently unavailable.",
      timedOut ? 504 : 503,
    );
  }

  if (!response.ok) {
    const requestId = response.headers.get("x-request-id") ?? undefined;
    const messages: Record<number, string> = {
      401: "The workspace is not authorized to use the research service.",
      403: "The workspace is not authorized to use the research service.",
      422: "Review the company, period, and research question.",
      429: "The research service is at capacity. Try again shortly.",
    };
    throw new BackendRequestError(
      messages[response.status] ?? "The research service could not complete this request.",
      response.status,
      requestId,
    );
  }
  return response;
}

export function errorResponse(error: unknown): NextResponse {
  if (error instanceof BackendRequestError) {
    return NextResponse.json(
      { error: error.message, requestId: error.requestId },
      { status: error.status },
    );
  }
  return NextResponse.json(
    { error: "The research service could not complete this request." },
    { status: 500 },
  );
}

export function backendUrl(path: string): string {
  return `${API_BASE}${path}`;
}
