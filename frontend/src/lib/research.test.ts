import { describe, expect, it } from "vitest";
import { citationHref, normalizePeriod, parseTickers, validPeriod, validTickers } from "./research";

describe("research request helpers", () => {
  it("normalizes and deduplicates ticker filters", () => {
    expect(parseTickers(" nvda, AMZN, nvda ")).toEqual(["NVDA", "AMZN"]);
    expect(validTickers("NVDA, BRK.B")).toBe(true);
    expect(validTickers("<script>")).toBe(false);
  });

  it("normalizes periods to the backend contract", () => {
    expect(normalizePeriod("q3 2026")).toBe("Q3-2026");
    expect(validPeriod("FY 2025")).toBe(true);
    expect(validPeriod("summer 2025")).toBe(false);
  });

  it("keeps document paths behind the same-origin source redirect", () => {
    const href = citationHref({ doc_id: "1", highlight_url: "/documents/1/viewer" });
    expect(href).toBe("/api/source?path=%2Fdocuments%2F1%2Fviewer");
  });
});
