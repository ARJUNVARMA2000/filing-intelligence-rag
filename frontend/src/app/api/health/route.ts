import { backendFetch } from "../_lib/backend";

export const runtime = "nodejs";

async function fetchJson(path: string, timeoutMs: number): Promise<unknown> {
  const response = await backendFetch(path, {}, timeoutMs);
  return response.json();
}

export async function GET(): Promise<Response> {
  const [readyResult, dataResult] = await Promise.allSettled([
    fetchJson("/health/ready", 3_500),
    fetchJson("/health/data", 6_000),
  ]);

  let ready = false;
  let indexChunks = 0;
  let data = null;

  if (readyResult.status === "fulfilled") {
    const payload = readyResult.value as { status?: string; index_chunks?: number };
    ready = payload.status === "ready" && Number(payload.index_chunks) > 0;
    indexChunks = Number(payload.index_chunks) || 0;
  }
  if (dataResult.status === "fulfilled") data = dataResult.value;

  return Response.json(
    { ready, indexChunks, data },
    { status: ready ? 200 : 503, headers: { "Cache-Control": "private, max-age=20" } },
  );
}
