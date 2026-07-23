import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach, afterEach } from "vitest";
import Ops from "./Ops";

const SETTINGS = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "local", max_attempts: 5, worker_interval_min: 5,
  enabled: false, discord_webhook_url: "",
  notify_enabled: false,
};
const STATUS = {
  activity: { collector: null, worker: { stage: "요약 중", detail: "토스 · 백엔드", progress: "4/20" }, research: [] },
  counts: { pending: 7, done: 3, failed: 0, skipped: 0, research_running: 1 },
  llm_health: "ok", enabled: true, next_ticks: { collect_hour: 9, worker_interval_min: 5 },
};

let putBody: Record<string, unknown> | null = null;
function mockFetch(statusOverride?: unknown) {
  return vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    let body: unknown = {};
    if (u.includes("claude-check")) body = { ok: true, reply: "OK" };
    else if (u.includes("/api/health")) body = { status: "ok" };
    else if (u.includes("/api/status")) body = statusOverride ?? STATUS;
    else if (u.includes("/api/collect/run")) body = { scraped: 1, inserted: 1 };
    else if (u.includes("/api/collect/worker/run")) body = { claimed: 0, done: 0, failed: 0, skipped_tick: false };
    else if (u.includes("/api/runs")) body = {
      items: [
        { id: 2, pipeline: "collector", ref: "", label: "", trigger: "scheduled",
          status: "ok", result: { scraped: 43, inserted: 43 }, error: "",
          started_at: "2026-07-23T09:00:00Z", finished_at: "2026-07-23T09:00:03Z", duration_ms: 3000 },
      ],
    };
    else if (u.includes("/api/notify/run")) body = { picked: 3, sent: 2, skipped: 1 };
    else if (u.includes("/api/settings")) {
      if (init?.method === "PUT") { putBody = JSON.parse(init.body as string); body = putBody; }
      else body = SETTINGS;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  });
}

beforeEach(() => { putBody = null; global.fetch = mockFetch() as unknown as typeof fetch; });
afterEach(() => vi.restoreAllMocks());

test("summary strip merges health probes and live status", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("API ok")).toBeTruthy());
  expect(screen.getByText("Claude ok")).toBeTruthy();
  expect(screen.getByText("LLM ok")).toBeTruthy();
  expect(screen.getByText(/백로그 7/)).toBeTruthy();
  // 라이브 파이프라인 — 실행 중 워커
  expect(screen.getByText("요약 중")).toBeTruthy();
  expect(screen.getByText(/4\/20/)).toBeTruthy();
});

test("loads settings, save disabled until dirty, then PUTs edited value", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  const save = screen.getByRole("button", { name: "저장" }) as HTMLButtonElement;
  expect(save.disabled).toBe(true);
  fireEvent.change(screen.getByLabelText("배치 크기"), { target: { value: "30" } });
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  await waitFor(() => expect(putBody?.batch_size).toBe(30));
});

test("manual run buttons disabled while dirty", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("배치 크기"), { target: { value: "30" } });
  expect((screen.getByRole("button", { name: "지금 수집" }) as HTMLButtonElement).disabled).toBe(true);
});

test("idle pipeline shows idle rows", async () => {
  global.fetch = mockFetch({ ...STATUS, activity: { collector: null, worker: null, research: [] } }) as unknown as typeof fetch;
  render(<Ops />);
  await waitFor(() => expect(screen.getAllByText(/idle/i).length).toBeGreaterThan(0));
});

test("실행 로그 카드가 최근 실행을 렌더한다", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("실행 로그")).toBeTruthy());
  expect(screen.getByText("스크레이핑 43·적재 43")).toBeTruthy();
  expect(screen.getByText("자동")).toBeTruthy();
});

test("수동 수집 후 실행 로그를 재조회한다", async () => {
  const fetchSpy = vi.fn(mockFetch());
  global.fetch = fetchSpy as unknown as typeof fetch;
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("실행 로그")).toBeTruthy());
  const before = fetchSpy.mock.calls.filter(([u]) => String(u).includes("/api/runs")).length;
  fireEvent.click(screen.getByText("지금 수집"));
  await waitFor(() => {
    const after = fetchSpy.mock.calls.filter(([u]) => String(u).includes("/api/runs")).length;
    expect(after).toBeGreaterThan(before);
  });
});

test("알림 활성화 토글이 저장 페이로드에 담긴다", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByLabelText("알림 활성화")).toBeTruthy());
  fireEvent.click(screen.getByLabelText("알림 활성화"));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.notify_enabled).toBe(true);
});

test("지금 알림 발송 결과를 문구로 보여준다", async () => {
  render(<Ops />);
  await waitFor(() => expect(screen.getByText("지금 알림 발송")).toBeTruthy());
  fireEvent.click(screen.getByText("지금 알림 발송"));
  await waitFor(() => expect(screen.getByText(/발송 2건/)).toBeTruthy());
});
