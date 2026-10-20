import { expect, test, vi } from "vitest";
import { createBrowserHistory, resolvePath } from "@remix-run/router";
import { matchRoutes } from "react-router-dom";
import { isJobSegment, jobPath } from "./jobPath";
import { getJob } from "./api";

const unsafe = ["", ".", "..", "../x", "../../\\\\evil.example/x", "/x", "\\x",
  "//evil.example", "https://evil.example", "a/b", "a\\b", "%2f", "%5C", "%2e%2e",
  "a%20b", "%25", "%252f", "%255c", "%252e%252e", "%", "%2", "%GG", "x\n", "x\u0000"];

test.each(unsafe)("blocks ambiguous segment %j for both source and ID before fetch", async value => {
  expect(isJobSegment(value)).toBe(false);
  expect(jobPath("wanted", value)).toBeNull();
  expect(jobPath(value, "123")).toBeNull();
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  await expect(getJob("wanted", value)).rejects.toThrow();
  await expect(getJob(value, "123")).rejects.toThrow();
  expect(fetchMock).not.toHaveBeenCalled();
  vi.unstubAllGlobals();
});

test.each(["123", "00123", "abc-123_4", "jump-it", "공고 42", "a.b", "a:b", "a?b#c", "a@b+"])(
  "preserves nonnumeric TEXT ID %j through URL, actual route matcher and API", async value => {
    const path = jobPath("wanted", value)!;
    const url = new URL(path, "https://app.example");
    expect(url.origin).toBe("https://app.example");
    expect(url.search).toBe("");
    expect(url.hash).toBe("");
    const params = matchRoutes([{ path: "/jobs/:source/:jobId" }], url.pathname)![0].params;
    expect(params).toEqual({ source: "wanted", jobId: value });
    const fetchMock = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ job: { source: params.source, job_id: params.jobId } }) });
    vi.stubGlobal("fetch", fetchMock);
    const detail = await getJob(params.source!, params.jobId!);
    const apiUrl = new URL(fetchMock.mock.calls[0][0], url.origin);
    expect(apiUrl.pathname.split("/").slice(-2).map(decodeURIComponent)).toEqual(["wanted", value]);
    expect(detail.job.job_id).toBe(value);
    vi.unstubAllGlobals();
  });

test("installed browser history reproduces old external-origin fallback only with mock location", () => {
  const assign = vi.fn();
  const pushState = vi.spyOn(window.history, "pushState").mockImplementation(() => {
    throw new DOMException("cross-origin", "SecurityError");
  });
  const mockWindow = { history: window.history, document: window.document,
    location: { pathname: "/jobs", search: "", hash: "", assign }, addEventListener: vi.fn() };
  const history = createBrowserHistory({ window: mockWindow as unknown as Window });
  const payload = "../../\\\\evil.example/x";
  const oldPath = resolvePath(`/jobs/wanted/${payload}`);
  history.push(oldPath);
  expect(new URL(assign.mock.calls[0][0], "https://app.example").origin).toBe("https://evil.example");
  assign.mockClear();
  expect(jobPath("wanted", payload)).toBeNull();
  expect(assign).not.toHaveBeenCalled();
  pushState.mockRestore();
});
