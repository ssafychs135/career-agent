import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "./App";

const STATUS = {
  activity: { collector: null, worker: null, research: [] },
  counts: { pending: 0, done: 0, failed: 0, skipped: 0, research_running: 0 },
  enabled: true, next_ticks: { collect_hour: 9, worker_interval_min: 5 },
};
const SETTINGS = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "claude", max_attempts: 5, worker_interval_min: 5,
  enabled: true, discord_webhook_url: "",
};

beforeEach(() => {
  window.history.replaceState(null, "", "/");
  global.fetch = vi.fn((url: RequestInfo | URL) => {
    const u = String(url);
    const body = u.includes("claude-check") ? { ok: true, reply: "OK" }
      : u.includes("/api/status") ? STATUS
      : u.includes("/api/settings") ? SETTINGS
      : u.includes("/api/runs") ? { items: [] }
      : { status: "ok" };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }) as unknown as typeof fetch;
});

test.each(["/settings", "/status"])("legacy %s replaces rather than appends history", async path => {
  window.history.replaceState({ marker: "legacy" }, "", path);
  const length = window.history.length;
  render(<App />);
  await waitFor(() => expect(window.location.pathname).toBe("/"));
  expect(window.history.length).toBe(length);
  await screen.findByText("운영");
});

test.each(["wanted", "jumpit"])("%s click, reload mount and back/forward preserve encoded API keys", async source => {
  const job_id = "공고 001?+#";
  const job = { source, job_id, company: "라우터 회귀", title: "라우터 상세", url: "https://example.test", locations: "서울", min_career: 0, max_career: 3, tech_stacks: [], status: "open", collected_at: "2026-10-21" };
  const fetchMock = vi.fn(async (url: RequestInfo | URL) => ({ ok: true, json: async () =>
    String(url).startsWith("/api/jobs?") ? { items: [job], total: 1, limit: 100, offset: 0 }
      : String(url).startsWith("/api/jobs/") ? { job, companyResearch: null, jobResearch: null }
      : { items: [] } }));
  vi.stubGlobal("fetch", fetchMock);
  window.history.replaceState(null, "", "/jobs");
  const view = render(<App />);
  fireEvent.click(await screen.findByText("라우터 회귀"));
  fireEvent.click(await screen.findByTestId("job-link"));
  await screen.findByTestId("job-title");
  const detailPath = `/jobs/${source}/${encodeURIComponent(job_id)}`;
  expect(window.location.pathname).toBe(detailPath);
  expect(fetchMock).toHaveBeenCalledWith(`/api${detailPath}`);
  window.history.back();
  await waitFor(() => expect(window.location.pathname).toBe("/jobs"));
  await waitFor(() => expect(screen.queryByTestId("job-title")).toBeNull());
  window.history.forward();
  await screen.findByTestId("job-title");
  expect(window.location.pathname).toBe(detailPath);
  view.unmount();
  fetchMock.mockClear();
  render(<App />); // A fresh mount at the existing browser URL models SPA reload hydration.
  await screen.findByTestId("job-title");
  expect(fetchMock).toHaveBeenCalledWith(`/api${detailPath}`);
  vi.unstubAllGlobals();
});

test("routes / to the ops dashboard with merged health summary", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText("운영")).toBeTruthy());
  expect(screen.getByText("API ok")).toBeTruthy();
  expect(screen.getByText("Claude ok")).toBeTruthy();
});
