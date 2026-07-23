import { test, expect } from "vitest";
import {
  pipelineLabel, triggerLabel, statusClass, runSummary, durationLabel, relativeTime,
} from "./runsFormat";
import type { RunLogItem } from "./runsApi";

function item(over: Partial<RunLogItem>): RunLogItem {
  return {
    id: 1, pipeline: "collector", ref: "", label: "", trigger: "manual",
    status: "ok", result: {}, error: "", started_at: "", finished_at: "", duration_ms: 0,
    ...over,
  };
}

test("labels and status class", () => {
  expect(pipelineLabel("collector")).toBe("수집기");
  expect(pipelineLabel("worker")).toBe("요약");
  expect(pipelineLabel("research")).toBe("리서치");
  expect(triggerLabel("scheduled")).toBe("자동");
  expect(triggerLabel("manual")).toBe("수동");
  expect(statusClass("ok")).toBe("rdot-ok");
  expect(statusClass("failed")).toBe("rdot-bad");
  expect(statusClass("skipped")).toBe("rdot-skip");
});

test("collector summary", () => {
  expect(runSummary(item({ pipeline: "collector", result: { scraped: 43, inserted: 43 } })))
    .toBe("스크레이핑 43·적재 43");
});

test("worker summary variants", () => {
  expect(runSummary(item({ pipeline: "worker", result: { done: 5, failed: 0 } })))
    .toBe("요약 5건");
  expect(runSummary(item({ pipeline: "worker", result: { done: 5, failed: 2 } })))
    .toBe("요약 5건·실패 2");
  expect(runSummary(item({ pipeline: "worker", status: "skipped", result: { skipped_tick: true } })))
    .toBe("건너뜀·LLM 대기");
});

test("research summary variants", () => {
  expect(runSummary(item({ pipeline: "research", label: "미스릴", status: "ok" })))
    .toBe("미스릴 완료");
  expect(runSummary(item({ pipeline: "research", label: "미스릴", status: "skipped" })))
    .toBe("미스릴 · 캐시");
  expect(runSummary(item({ pipeline: "research", label: "미스릴", status: "failed" })))
    .toBe("미스릴 · 실패");
});

test("duration and relative time", () => {
  expect(durationLabel(850)).toBe("850ms");
  expect(durationLabel(1500)).toBe("1.5s");
  const now = new Date("2026-07-23T10:00:00Z").getTime();
  expect(relativeTime("2026-07-23T09:59:30Z", now)).toBe("30초 전");
  expect(relativeTime("2026-07-23T09:55:00Z", now)).toBe("5분 전");
  expect(relativeTime("2026-07-23T08:00:00Z", now)).toBe("2시간 전");
});
