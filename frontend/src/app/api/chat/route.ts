import { backendFetch, errorResponse } from "../_lib/backend";

export const runtime = "nodejs";

export async function POST(request: Request): Promise<Response> {
  try {
    const body = await request.text();
    if (body.length > 32_000) {
      return Response.json({ error: "The research request is too large." }, { status: 413 });
    }
    const response = await backendFetch("/chat", { method: "POST", body });
    return Response.json(await response.json(), {
      headers: { "X-Request-ID": response.headers.get("x-request-id") ?? "" },
    });
  } catch (error) {
    return errorResponse(error);
  }
}
