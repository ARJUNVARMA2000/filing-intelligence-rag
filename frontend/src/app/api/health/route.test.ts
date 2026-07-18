import { beforeEach, describe, expect, it, vi } from "vitest";

const backendFetch = vi.fn();

vi.mock("../_lib/backend", () => ({ backendFetch }));

describe("health route", () => {
  beforeEach(() => backendFetch.mockReset());

  it("consumes readiness before waiting for the slower data request", async () => {
    let dataSettled = false;
    backendFetch.mockImplementation((path: string) => {
      if (path === "/health/ready") {
        return Promise.resolve({
          json: async () => {
            expect(dataSettled).toBe(false);
            return { status: "ready", index_chunks: 4_967 };
          },
        });
      }
      return new Promise((resolve) => {
        setTimeout(() => {
          dataSettled = true;
          resolve({ json: async () => ({ documents: 128, chunks: 4_967 }) });
        }, 10);
      });
    });

    const { GET } = await import("./route");
    const response = await GET();

    expect(response.status).toBe(200);
    await expect(response.json()).resolves.toMatchObject({
      ready: true,
      indexChunks: 4_967,
      data: { documents: 128, chunks: 4_967 },
    });
  });
});
