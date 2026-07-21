import { vi, test, expect, beforeEach } from "vitest";
import { getJobs, getJob } from "./api";

beforeEach(() => {
  vi.restoreAllMocks();
});

test("getJobs builds query string and returns page", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ items: [], total: 0, limit: 20, offset: 0 }),
  });
  global.fetch = fetchMock as unknown as typeof fetch;

  const page = await getJobs({ keyword: "dev", status: "open", limit: 20, offset: 0 });
  expect(page.total).toBe(0);
  const url = String(fetchMock.mock.calls[0][0]);
  expect(url).toContain("/api/jobs?");
  expect(url).toContain("keyword=dev");
  expect(url).toContain("status=open");
});

test("getJobs omits empty params", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () => Promise.resolve({ items: [], total: 0, limit: 20, offset: 0 }),
  });
  global.fetch = fetchMock as unknown as typeof fetch;

  await getJobs({ status: "", keyword: "dev" });
  const url = String(fetchMock.mock.calls[0][0]);
  expect(url).not.toContain("status=");
  expect(url).toContain("keyword=dev");
});

test("getJob fetches detail endpoint and returns merged shape", async () => {
  const fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    json: () =>
      Promise.resolve({
        job: { source: "saramin", job_id: "1", company: "Acme" },
        companyResearch: null,
        jobResearch: null,
      }),
  });
  global.fetch = fetchMock as unknown as typeof fetch;

  const res = await getJob("saramin", "1");
  expect(res.job.source).toBe("saramin");
  expect(res.companyResearch).toBeNull();
  expect(String(fetchMock.mock.calls[0][0])).toBe("/api/jobs/saramin/1");
});

test("getJob throws on 404", async () => {
  global.fetch = vi.fn().mockResolvedValue({ ok: false }) as unknown as typeof fetch;
  await expect(getJob("x", "y")).rejects.toThrow();
});
