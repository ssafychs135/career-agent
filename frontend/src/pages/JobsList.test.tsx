import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { vi, test, expect, beforeEach, type Mock } from "vitest";
import JobsList from "./JobsList";
import { getJobs } from "../api";

vi.mock("../api");

beforeEach(() => {
  (getJobs as Mock).mockResolvedValue({
    items: [
      {
        source: "saramin",
        job_id: "1",
        company: "Acme",
        title: "백엔드 개발자",
        url: "http://x",
        locations: "서울, 부산",
        min_career: 0,
        max_career: 3,
        status: "open",
        collected_at: "2026-07-20",
        tech_stacks: ["python"],
        has_company_research: true,
        has_job_research: false,
      },
    ],
    total: 1,
    limit: 20,
    offset: 0,
  });
});

test("renders jobs and links to detail", async () => {
  render(
    <MemoryRouter>
      <JobsList />
    </MemoryRouter>,
  );
  await waitFor(() => expect(screen.getByText("백엔드 개발자")).toBeTruthy());
  const link = screen.getByTestId("job-link") as HTMLAnchorElement;
  expect(link.getAttribute("href")).toBe("/jobs/saramin/1");
  expect(screen.getByTestId("job-total").textContent).toContain("1");
});

test("applies keyword filter live (no submit button)", async () => {
  render(
    <MemoryRouter>
      <JobsList />
    </MemoryRouter>,
  );
  await waitFor(() => expect(getJobs).toHaveBeenCalled());
  // Typing alone reloads the list (debounced) — no search button to press.
  fireEvent.change(screen.getByTestId("filter-keyword"), { target: { value: "backend" } });
  await waitFor(() =>
    expect(getJobs).toHaveBeenLastCalledWith(expect.objectContaining({ keyword: "backend", offset: 0 })),
  );
});
