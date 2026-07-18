import { backendUrl } from "../_lib/backend";

const DOCUMENT_PATH = /^\/documents\/[A-Za-z0-9%._~!$&'()*+,;=:@/-]+$/;

export function GET(request: Request): Response {
  const path = new URL(request.url).searchParams.get("path") ?? "";
  if (!DOCUMENT_PATH.test(path) || path.includes("..")) {
    return Response.json({ error: "Invalid source path." }, { status: 400 });
  }
  return Response.redirect(backendUrl(path), 307);
}
