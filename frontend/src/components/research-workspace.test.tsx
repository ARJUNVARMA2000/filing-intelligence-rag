import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ResearchWorkspace } from "./research-workspace";

const response = (body: object, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });

describe("ResearchWorkspace", () => {
  beforeEach(() => {
    Element.prototype.scrollIntoView = vi.fn();
    window.scrollTo = vi.fn();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("resolves scope, builds a brief, and preserves the model source id", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async (input) => {
      const url = String(input);
      if (url === "/api/health") {
        return response({ ready: true, indexChunks: 4967, data: { documents: 128, coverage: {} } });
      }
      if (url === "/api/parse-query") {
        return response({ tickers: ["NVDA"], period: "Q3-2026", needs_clarification: false });
      }
      if (url === "/api/chat") {
        return response({
          answer: "NVIDIA reported record revenue of **$57.0 billion** [S3].",
          citations: [{
            source_id: "S3",
            doc_id: "nvda-q3",
            chunk_id: "revenue",
            ticker: "NVDA",
            period: "Q3-2026",
            doc_title: "NVIDIA Q3 2026 earnings release",
            page: 10,
            text: "Record quarterly revenue was $57.0 billion.",
            relevance_score: 0.93,
            highlight_url: "/documents/nvda-q3/chunks/revenue/viewer",
          }],
        });
      }
      throw new Error(`Unexpected fetch: ${url}`);
    });

    const user = userEvent.setup();
    render(<ResearchWorkspace />);
    await user.type(screen.getByRole("textbox", { name: "Research question" }), "What was NVIDIA revenue in Q3 2026?");
    await user.click(screen.getByRole("button", { name: "Build the brief" }));

    expect(await screen.findByText("$57.0 billion")).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Inspect source 3" })).toHaveTextContent("S3");
    expect(screen.getByText("NVIDIA Q3 2026 earnings release")).toBeInTheDocument();
    expect(screen.getByText("93%")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Inspect source 3" }));
    expect(screen.getByText("Record quarterly revenue was $57.0 billion.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "View cited page" })).toHaveAttribute(
      "href",
      "/api/source?path=%2Fdocuments%2Fnvda-q3%2Fchunks%2Frevenue%2Fviewer",
    );
    expect(screen.getByRole("link", { name: "View cited page" })).toHaveAttribute("target", "_blank");
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });
});
