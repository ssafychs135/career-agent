import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "./App";

const STATUS = {
  activity: { collector: null, worker: null, research: [] },
  counts: { pending: 0, done: 0, failed: 0, skipped: 0, research_running: 0 },
  llm_health: "ok", enabled: true, next_ticks: { collect_hour: 9, worker_interval_min: 5 },
};
const SETTINGS = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "local", max_attempts: 5, worker_interval_min: 5,
  enabled: true, discord_webhook_url: "",
};

beforeEach(() => {
  global.fetch = vi.fn((url: RequestInfo | URL) => {
    const u = String(url);
    const body = u.includes("claude-check") ? { ok: true, reply: "OK" }
      : u.includes("/api/status") ? STATUS
      : u.includes("/api/settings") ? SETTINGS
      : { status: "ok" };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }) as unknown as typeof fetch;
});

test("routes / to the ops dashboard with merged health summary", async () => {
  render(<App />);
  await waitFor(() => expect(screen.getByText("운영")).toBeTruthy());
  expect(screen.getByText("API ok")).toBeTruthy();
  expect(screen.getByText("Claude ok")).toBeTruthy();
});
