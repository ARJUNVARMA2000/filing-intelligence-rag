import { describe, expect, it } from "vitest";
import { GET } from "./route";

describe("source redirect", () => {
  it("redirects an allowlisted viewer path to the backend", () => {
    const response = GET(
      new Request(
        "http://localhost/api/source?path=%2Fdocuments%2Fnvda-q3%2Fchunks%2Frevenue%2Fviewer",
      ),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://127.0.0.1:8000/documents/nvda-q3/chunks/revenue/viewer",
    );
  });

  it("accepts decoded corpus paths containing spaces", () => {
    const sourcePath =
      "/documents/NVDA_Q3-2026_NVIDIA - Q3 2026 - Conference Call Deck/" +
      "chunks/NVDA_Q3-2026_NVIDIA - Q3 2026 - Conference Call Deck_chunk_5/viewer";
    const response = GET(
      new Request(`http://localhost/api/source?path=${encodeURIComponent(sourcePath)}`),
    );

    expect(response.status).toBe(307);
    expect(response.headers.get("location")).toBe(
      "http://127.0.0.1:8000/documents/" +
        "NVDA_Q3-2026_NVIDIA%20-%20Q3%202026%20-%20Conference%20Call%20Deck/" +
        "chunks/" +
        "NVDA_Q3-2026_NVIDIA%20-%20Q3%202026%20-%20Conference%20Call%20Deck_chunk_5/" +
        "viewer",
    );
  });

  it("rejects traversal and non-document destinations", () => {
    const traversal = GET(
      new Request("http://localhost/api/source?path=%2Fdocuments%2F..%2Fsecrets"),
    );
    const external = GET(
      new Request("http://localhost/api/source?path=https%3A%2F%2Fexample.com%2Fsource.pdf"),
    );

    expect(traversal.status).toBe(400);
    expect(external.status).toBe(400);
  });
});
