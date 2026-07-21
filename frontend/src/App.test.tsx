import { render, screen, waitFor } from "@testing-library/react";
import { vi, test, expect, beforeEach } from "vitest";
import App from "./App";

beforeEach(() => {
  global.fetch = vi.fn((url: RequestInfo | URL) =>
    Promise.resolve({
      ok: true,
      json: () =>
        Promise.resolve(
          String(url).includes("claude-check")
            ? { ok: true, reply: "OK" }
            : { status: "ok" },
        ),
    }),
  ) as unknown as typeof fetch;
});

test("renders health and claude status", async () => {
  render(<App />);
  await waitFor(() =>
    expect(screen.getByTestId("health").textContent).toBe("ok"),
  );
  expect(screen.getByTestId("claude").textContent).toBe("OK");
});
