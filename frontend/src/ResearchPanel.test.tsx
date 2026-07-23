import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { vi, test, expect } from "vitest";
import { ResearchPanel } from "./ResearchPanel";

test("shows existing research", () => {
  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={{ status: "done", overview: "핀테크" }}
      jobResearch={{ status: "done", tech_detail: "Spring 기반" }}
      refetch={vi.fn()}
    />,
  );
  expect(screen.getByText(/핀테크/)).toBeTruthy();
  expect(screen.getByText(/Spring 기반/)).toBeTruthy();
});

test("triggers research and polls until done", async () => {
  const trigger = vi.fn().mockResolvedValue({ status: "running" });
  const refetch = vi
    .fn()
    .mockResolvedValueOnce({
      companyResearch: { status: "running" },
      jobResearch: { status: "running" },
    })
    .mockResolvedValueOnce({
      companyResearch: { status: "done", overview: "핀테크" },
      jobResearch: { status: "done", tech_detail: "Spring 기반" },
    });

  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={null}
      jobResearch={null}
      refetch={refetch}
      trigger={trigger}
      pollMs={0}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /리서치/ }));
  expect(trigger).toHaveBeenCalledWith("wanted", "42");
  await waitFor(() => expect(screen.getByText(/Spring 기반/)).toBeTruthy());
});

test("이미 running인 상태로 마운트되면 클릭 없이도 폴링해 갱신한다", async () => {
  // 재마운트·새로고침·다른 경로에서 시작된 리서치 — 예전엔 클릭해야만 폴링해서 멈춰 보였다.
  const refetch = vi.fn().mockResolvedValue({
    companyResearch: { status: "done", overview: "핀테크" },
    jobResearch: { status: "done", tech_detail: "Spring 기반" },
  });

  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={{ status: "running" }}
      jobResearch={{ status: "running" }}
      refetch={refetch}
      trigger={vi.fn()}
      pollMs={0}
    />,
  );

  await waitFor(() => expect(screen.getByText(/Spring 기반/)).toBeTruthy());
  expect(refetch).toHaveBeenCalled();
});

test("done 상태에서는 폴링하지 않는다", async () => {
  const refetch = vi.fn();
  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={{ status: "done", overview: "핀테크" }}
      jobResearch={{ status: "done", tech_detail: "x" }}
      refetch={refetch}
      trigger={vi.fn()}
      pollMs={0}
    />,
  );
  await new Promise((r) => setTimeout(r, 20));
  expect(refetch).not.toHaveBeenCalled();
});

function renderRunning(getActivity: () => Promise<unknown[]>, company?: string) {
  const refetch = vi.fn().mockResolvedValue({
    companyResearch: { status: "running" },
    jobResearch: { status: "running" },
  });
  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      company={company}
      companyResearch={{ status: "running" }}
      jobResearch={{ status: "running" }}
      refetch={refetch}
      trigger={vi.fn()}
      getActivity={getActivity as never}
      pollMs={0}
    />,
  );
}

test("진행 단계를 표시한다 (공고 리서치)", async () => {
  const getActivity = vi
    .fn()
    .mockResolvedValue([
      { detail_key: "wanted:42", stage: "공고 리서치 중", detail: "채용 공고 분석" },
    ]);
  renderRunning(getActivity);
  await waitFor(() =>
    expect(screen.getByTestId("research-stage").textContent).toContain("공고 리서치 중"),
  );
  expect(screen.getByTestId("research-stage").textContent).toContain("채용 공고 분석");
});

test("공고 항목이 아직 없으면 기업 리서치 단계로 폴백한다", async () => {
  // research_job은 기업 리서치를 먼저 돌린다 — 그동안 activity 키는 기업명이다.
  const getActivity = vi
    .fn()
    .mockResolvedValue([{ detail_key: "미스릴", stage: "기업 리서치 중", detail: "" }]);
  renderRunning(getActivity, "미스릴");
  await waitFor(() =>
    expect(screen.getByTestId("research-stage").textContent).toContain("기업 리서치 중"),
  );
});

test("단계 정보가 없으면 기본 문구를 유지한다", async () => {
  renderRunning(vi.fn().mockResolvedValue([]));
  await waitFor(() => expect(screen.getByTestId("research-stage")).toBeTruthy());
  expect(screen.getByTestId("research-stage").textContent).toContain("리서치 중…");
});

test("failed research shows retry button, not a dead end", () => {
  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={null}
      jobResearch={{ status: "failed" }}
      refetch={vi.fn()}
    />,
  );
  expect(screen.getByText("리서치 실패")).toBeTruthy();
  expect(screen.getByRole("button", { name: /재시도/ })).toBeTruthy();
});

test("done research shows force re-research button", async () => {
  const trigger = vi.fn().mockResolvedValue({ status: "running" });
  const refetch = vi.fn().mockResolvedValue({
    companyResearch: { status: "done", overview: "핀테크" },
    jobResearch: { status: "done", tech_detail: "x" },
  });

  render(
    <ResearchPanel
      source="wanted"
      jobId="42"
      companyResearch={null}
      jobResearch={{ status: "done", tech_detail: "x" }}
      refetch={refetch}
      trigger={trigger}
      pollMs={0}
    />,
  );

  fireEvent.click(screen.getByRole("button", { name: /재리서치/ }));
  await waitFor(() => expect(trigger).toHaveBeenCalledWith("wanted", "42", true));
});
