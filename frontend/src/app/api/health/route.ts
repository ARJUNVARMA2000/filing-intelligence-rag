import { backendFetch } from "../_lib/backend";

export const runtime = "nodejs";

export async function GET(): Promise<Response> {
  const [readyResult, dataResult] = await Promise.allSettled([
    backendFetch("/health/ready", {}, 3_500),
    backendFetch("/health/data", {}, 6_000),
  ]);

  let ready = false;
  let indexChunks = 0;
  let data = null;

  if (readyResult.status === "fulfilled") {
    const payload = (await readyResult.value.json()) as { status?: string; index_chunks?: number };
    ready = payload.status === "ready" && Number(payload.index_chunks) > 0;
    indexChunks = Number(payload.index_chunks) || 0;
  }
  if (dataResult.status === "fulfilled") data = await dataResult.value.json();

  return Response.json(
    { ready, indexChunks, data },
    { status: ready ? 200 : 503, headers: { "Cache-Control": "private, max-age=20" } },
  );
}
