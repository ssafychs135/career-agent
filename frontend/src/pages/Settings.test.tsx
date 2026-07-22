import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import Settings from "./Settings";
import * as api from "../settingsApi";

const seed: api.Settings = {
  keywords: ["백엔드"], allowed_wanted_categories: [518], max_career_years: 2,
  max_pages: 9999, collect_hour: 9, batch_size: 20, model: "kanana",
  summary_backend: "local", max_attempts: 5, worker_interval_min: 5,
  enabled: false, discord_webhook_url: "",
};

beforeEach(() => {
  vi.spyOn(api, "getSettings").mockResolvedValue({ ...seed });
  vi.spyOn(api, "putSettings").mockImplementation(async (s) => s);
});

test("loads settings and disables save until dirty", async () => {
  render(<Settings />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  expect((screen.getByRole("button", { name: "저장" }) as HTMLButtonElement).disabled).toBe(true);
});

test("editing enables save and PUTs", async () => {
  render(<Settings />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("배치 크기"), { target: { value: "30" } });
  const save = screen.getByRole("button", { name: "저장" }) as HTMLButtonElement;
  expect(save.disabled).toBe(false);
  fireEvent.click(save);
  await waitFor(() => expect(api.putSettings).toHaveBeenCalled());
  expect(api.putSettings.mock.calls[0][0].batch_size).toBe(30);
});

test("manual run buttons disabled while dirty", async () => {
  render(<Settings />);
  await waitFor(() => expect(screen.getByText("백엔드")).toBeTruthy());
  fireEvent.change(screen.getByLabelText("배치 크기"), { target: { value: "30" } });
  expect((screen.getByRole("button", { name: "지금 수집" }) as HTMLButtonElement).disabled).toBe(true);
});
