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
