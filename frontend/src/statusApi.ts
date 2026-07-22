export interface StatusResponse {
  activity: {
    collector: { stage: string; detail: string; progress: string } | null;
    worker: { stage: string; detail: string; progress: string } | null;
    research: { detail_key: string; stage: string; detail: string }[];
  };
  counts: { pending: number; done: number; failed: number; skipped: number; research_running: number };
  llm_health: "ok" | "down";
  enabled: boolean;
  next_ticks: { collect_hour: number; worker_interval_min: number };
}

export async function getStatus(): Promise<StatusResponse> {
  const r = await fetch("/api/status");
  if (!r.ok) throw new Error("status load failed");
  return r.json();
}
