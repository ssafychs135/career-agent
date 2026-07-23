import type { RunLogItem } from "./runsApi";

export function pipelineLabel(p: string): string {
  return p === "collector" ? "수집기" : p === "worker" ? "요약" : p === "notifier" ? "알림" : "리서치";
}

export function triggerLabel(t: string): string {
  return t === "scheduled" ? "자동" : "수동";
}

export function statusClass(s: string): string {
  return s === "ok" ? "rdot-ok" : s === "failed" ? "rdot-bad" : "rdot-skip";
}

export function runSummary(it: RunLogItem): string {
  const r = it.result as Record<string, number>;
  if (it.pipeline === "collector") {
    return `스크레이핑 ${r.scraped ?? 0}·적재 ${r.inserted ?? 0}`;
  }
  if (it.pipeline === "worker") {
    if (it.status === "skipped") return "건너뜀·LLM 대기";
    const failed = Number(r.failed ?? 0);
    const esc = Number(r.escalated ?? 0);
    return `요약 ${r.done ?? 0}건${failed ? `·실패 ${failed}` : ""}${esc ? `·승급 ${esc}` : ""}`;
  }
  if (it.pipeline === "notifier") {
    const skipped = Number(r.skipped ?? 0);
    return `발송 ${r.sent ?? 0}건${skipped ? ` · 건너뜀 ${skipped}` : ""}`;
  }
  const name = it.label || it.ref;
  if (it.status === "skipped") return `${name} · 캐시`;
  if (it.status === "failed") return `${name} · 실패`;
  return `${name} 완료`;
}

export function durationLabel(ms: number): string {
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(1)}s`;
}

export function relativeTime(iso: string, nowMs: number): string {
  const s = Math.max(0, Math.round((nowMs - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}초 전`;
  const m = Math.round(s / 60);
  if (m < 60) return `${m}분 전`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}시간 전`;
  return `${Math.round(h / 24)}일 전`;
}
