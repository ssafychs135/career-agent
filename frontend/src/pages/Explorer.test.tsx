import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi, test, expect, beforeEach, type Mock } from "vitest";
import Explorer from "./Explorer";
import { getJobs } from "../api";

vi.mock("../api");

const job = (over: Record<string, unknown>) => ({
  source: "wanted",
  job_id: "1",
  company: "뉴런웍스",
  title: "백엔드 엔지니어",
  url: "http://x",
  locations: "서울 강남구",
  min_career: 0,
  max_career: 3,
  status: "open",
  collected_at: "2026-07-20",
  tech_stacks: [],
  has_company_research: true,
  has_job_research: false,
  ...over,
});

beforeEach(() => {
  (getJobs as Mock).mockResolvedValue({
    items: [
      job({ job_id: "1", company: "뉴런웍스", title: "백엔드 엔지니어", locations: "서울 강남구" }),
      job({ job_id: "2", company: "뉴런웍스", title: "데이터 엔지니어", locations: "서울 강남구", has_job_research: true }),
      job({ source: "saramin", job_id: "9", company: "파스텔로", title: "ML 개발자", locations: "경기 성남시" }),
    ],
    total: 3,
    limit: 100,
    offset: 0,
  });
});

test("lists companies and reveals a company's jobs on select", async () => {
  render(
    <MemoryRouter>
      <Explorer />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("뉴런웍스")).toBeTruthy());
  expect(screen.getByText("파스텔로")).toBeTruthy();
  // 공고는 기업 선택 전까지 숨김
  expect(screen.queryByText("백엔드 엔지니어")).toBeNull();

  fireEvent.click(screen.getByText("뉴런웍스"));
  await waitFor(() => expect(screen.getByText("백엔드 엔지니어")).toBeTruthy());
  expect(screen.getByText("데이터 엔지니어")).toBeTruthy();
  // 다른 기업의 공고는 안 보임
  expect(screen.queryByText("ML 개발자")).toBeNull();
});

test("multi-select aggregates jobs from all selected companies", async () => {
  render(
    <MemoryRouter>
      <Explorer />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("뉴런웍스")).toBeTruthy());
  // 뉴런웍스 선택 → 그 공고만
  fireEvent.click(screen.getByText("뉴런웍스"));
  await waitFor(() => expect(screen.getByText("백엔드 엔지니어")).toBeTruthy());
  expect(screen.queryByText("ML 개발자")).toBeNull();
  // 파스텔로도 추가 선택 → 두 기업의 공고가 2계층에 합쳐짐
  fireEvent.click(screen.getByText("파스텔로"));
  await waitFor(() => expect(screen.getByText("ML 개발자")).toBeTruthy());
  expect(screen.getByText("백엔드 엔지니어")).toBeTruthy();
});

test("region filter narrows the company list", async () => {
  render(
    <MemoryRouter>
      <Explorer />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("파스텔로")).toBeTruthy());
  fireEvent.change(screen.getByTestId("filter-region"), { target: { value: "경기" } });
  await waitFor(() => expect(screen.queryByText("뉴런웍스")).toBeNull());
  expect(screen.getByText("파스텔로")).toBeTruthy();
});
