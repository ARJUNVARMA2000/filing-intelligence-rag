import { backendFetch, errorResponse } from "../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.text();
    if (body.length > 8_000) {
      return Response.json({ error: "The question is too large." }, { status: 413 });
    }
    const response = await backendFetch("/chat/parse-query", { method: "POST", body }, 25_000);
    return Response.json(await response.json(), {
      headers: { "X-Request-ID": response.headers.get("x-request-id") ?? "" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
