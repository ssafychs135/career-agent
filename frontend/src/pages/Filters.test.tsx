import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach, afterEach } from "vitest";
import Filters from "./Filters";

const SETTINGS = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "local", max_attempts: 5, worker_interval_min: 5,
  enabled: false, discord_webhook_url: "",
  allowed_regions: [] as string[], hidden_companies: [] as string[],
};
const FACETS = {
  regions: [{ name: "서울", count: 362 }, { name: "경기", count: 59 }],
  companies: [{ name: "미스릴", count: 3 }, { name: "토스", count: 2 }],
};

let putBody: Record<string, unknown> | null = null;
function mockFetch() {
  return vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    let body: unknown = {};
    if (u.includes("/api/facets")) body = FACETS;
    else if (u.includes("/api/settings")) {
      if (init?.method === "PUT") { putBody = JSON.parse(init.body as string); body = putBody; }
      else body = SETTINGS;
    }
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  });
}

beforeEach(() => { putBody = null; global.fetch = mockFetch() as unknown as typeof fetch; });
afterEach(() => vi.restoreAllMocks());

test("지역·기업 목록을 공고 수와 함께 보여준다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/서울/)).toBeTruthy());
  expect(screen.getByLabelText(/경기/)).toBeTruthy();
  expect(screen.getByLabelText(/미스릴/)).toBeTruthy();
  expect(screen.getByText(/362/)).toBeTruthy();
});

test("지역을 체크하면 allowed_regions에 담겨 저장된다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/서울/)).toBeTruthy());
  fireEvent.click(screen.getByLabelText(/서울/));
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.allowed_regions).toEqual(["서울"]);
});

test("기업 체크를 해제하면 hidden_companies에 담겨 저장된다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/미스릴/)).toBeTruthy());
  fireEvent.click(screen.getByLabelText(/미스릴/)); // 기본 체크됨 → 해제 = 숨김
  fireEvent.click(screen.getByRole("button", { name: "저장" }));
  await waitFor(() => expect(putBody).not.toBeNull());
  expect(putBody!.hidden_companies).toEqual(["미스릴"]);
});

test("검색으로 기업 목록을 좁힌다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/미스릴/)).toBeTruthy());
  fireEvent.change(screen.getByLabelText("기업 검색"), { target: { value: "토스" } });
  expect(screen.queryByLabelText(/미스릴/)).toBeNull();
  expect(screen.getByLabelText(/토스/)).toBeTruthy();
});

test("숨김 개수를 요약해 보여준다", async () => {
  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/미스릴/)).toBeTruthy());
  fireEvent.click(screen.getByLabelText(/미스릴/));
  expect(screen.getByText(/2개 중 1개 숨김/)).toBeTruthy();
});

test("체크 상태가 실제 설정을 반영한다 (지역=허용, 기업=표시)", async () => {
  global.fetch = vi.fn((url: RequestInfo | URL, init?: RequestInit) => {
    const u = String(url);
    const body = u.includes("/api/facets")
      ? FACETS
      : { ...SETTINGS, allowed_regions: ["서울"], hidden_companies: ["미스릴"] };
    return Promise.resolve({ ok: true, json: () => Promise.resolve(body) });
  }) as unknown as typeof fetch;

  render(<Filters />);
  await waitFor(() => expect(screen.getByLabelText(/서울/)).toBeTruthy());

  const chk = (re: RegExp) => screen.getByLabelText(re) as HTMLInputElement;
  expect(chk(/서울/).checked).toBe(true);    // 허용목록에 있음 → 체크
  expect(chk(/경기/).checked).toBe(false);   // 허용목록에 없음 → 해제
  expect(chk(/미스릴/).checked).toBe(false); // 숨김목록에 있음 → 해제
  expect(chk(/토스/).checked).toBe(true);    // 숨김목록에 없음 → 체크
});
