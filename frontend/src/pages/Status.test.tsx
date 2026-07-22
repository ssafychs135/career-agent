import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach, afterEach } from "vitest";
import Status from "./Status";
import * as api from "../statusApi";

const base: api.StatusResponse = {
  activity: { collector: null, worker: { stage: "요약 중", detail: "토스 · 백엔드", progress: "4/20" }, research: [] },
  counts: { pending: 7, done: 3, failed: 0, skipped: 0, research_running: 1 },
  llm_health: "ok", enabled: true, next_ticks: { collect_hour: 9, worker_interval_min: 5 },
};

beforeEach(() => { vi.spyOn(api, "getStatus").mockResolvedValue(base); });
afterEach(() => vi.restoreAllMocks());

test("renders running worker card and backlog", async () => {
  render(<Status />);
  await waitFor(() => expect(screen.getByText("요약 중")).toBeTruthy());
  expect(screen.getByText(/토스 · 백엔드/)).toBeTruthy();
  expect(screen.getByText(/4\/20/)).toBeTruthy();
  expect(screen.getByText(/7/)).toBeTruthy(); // pending 백로그
});

test("shows idle for empty pipeline", async () => {
  render(<Status />);
  await waitFor(() => expect(screen.getAllByText(/idle/i).length).toBeGreaterThan(0));
});
