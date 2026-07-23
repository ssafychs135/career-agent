export type Pipeline = "collector" | "worker" | "research" | "notifier";
export type RunStatus = "ok" | "failed" | "skipped";

export interface RunLogItem {
  id: number;
  pipeline: Pipeline;
  ref: string;
  label: string;
  trigger: "manual" | "scheduled";
  status: RunStatus;
  result: Record<string, unknown>;
  error: string;
  started_at: string;
  finished_at: string;
  duration_ms: number;
}

export async function getRuns(limit = 30): Promise<{ items: RunLogItem[] }> {
  const r = await fetch(`/api/runs?limit=${limit}`);
  if (!r.ok) throw new Error("runs load failed");
  return r.json();
}
