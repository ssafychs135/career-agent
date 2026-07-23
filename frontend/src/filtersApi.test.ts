import { vi, test, expect, afterEach } from "vitest";
import { getFacets } from "./filtersApi";

afterEach(() => vi.restoreAllMocks());

test("getFacets는 /api/facets를 호출해 목록을 반환한다", async () => {
  const body = {
    regions: [{ name: "서울", count: 362 }],
    companies: [{ name: "미스릴", count: 3 }],
  };
  global.fetch = vi.fn(() =>
    Promise.resolve({ ok: true, json: () => Promise.resolve(body) }),
  ) as unknown as typeof fetch;

  const r = await getFacets();
  expect(r.regions[0].name).toBe("서울");
  expect(r.companies[0].count).toBe(3);
  expect((global.fetch as unknown as ReturnType<typeof vi.fn>).mock.calls[0][0]).toBe("/api/facets");
});

test("실패하면 에러를 던진다", async () => {
  global.fetch = vi.fn(() => Promise.resolve({ ok: false })) as unknown as typeof fetch;
  await expect(getFacets()).rejects.toThrow();
});
