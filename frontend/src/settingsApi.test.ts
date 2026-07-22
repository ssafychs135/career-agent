import { vi, test, expect, afterEach } from "vitest";
import { getSettings, putSettings } from "./settingsApi";

afterEach(() => vi.restoreAllMocks());

test("getSettings fetches and parses", async () => {
  const body = { batch_size: 20, keywords: ["백엔드"] };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: () => Promise.resolve(body) }));
  const s = await getSettings();
  expect(s.batch_size).toBe(20);
});

test("putSettings throws typed error on 422", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
    ok: false, status: 422, json: () => Promise.resolve({ detail: [{ loc: ["body", "collect_hour"], msg: "bad" }] }),
  }));
  await expect(putSettings({} as never)).rejects.toMatchObject({ status: 422 });
});
