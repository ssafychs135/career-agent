import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach, type Mock } from "vitest";
import JobDetailView from "./JobDetailView";
import { getJob } from "../api";

vi.mock("../api");

beforeEach(() => {
  (getJob as Mock).mockResolvedValue({
    job: {
      source: "saramin",
      job_id: "1",
      company: "Acme",
      title: "백엔드 개발자",
      url: "http://x",
      locations: "서울",
      min_career: 0,
      max_career: 3,
      tech_stacks: ["python"],
      summary: "요약",
      status: "open",
      attempts: 0,
      collected_at: "2026-07-20",
      updated_at: null,
      closed_at: null,
    },
    companyResearch: { status: "done", overview: "안정적", stability: null, sources: null, researched_at: null },
    jobResearch: null,
  });
});

test("renders detail with research body", async () => {
  render(<JobDetailView source="saramin" jobId="1" />);
  await waitFor(() => expect(screen.getByTestId("job-title").textContent).toBe("백엔드 개발자"));
  expect(screen.getByTestId("job-company").textContent).toBe("Acme");
  expect(screen.getByText(/안정적/)).toBeTruthy();
  expect(getJob).toHaveBeenCalledWith("saramin", "1");
});

test("shows error when job missing", async () => {
  (getJob as Mock).mockRejectedValue(new Error("404"));
  render(<JobDetailView source="x" jobId="y" />);
  await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
});
