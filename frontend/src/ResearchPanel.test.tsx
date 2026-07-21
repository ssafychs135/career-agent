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
