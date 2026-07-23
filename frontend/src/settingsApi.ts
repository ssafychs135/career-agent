export interface Settings {
  keywords: string[];
  allowed_wanted_categories: number[];
  max_career_years: number;
  max_pages: number;
  collect_hour: number;
  batch_size: number;
  model: string;
  summary_backend: "local" | "claude";
  max_attempts: number;
  worker_interval_min: number;
  enabled: boolean;
  discord_webhook_url: string;
  allowed_regions: string[];
  hidden_companies: string[];
  notify_enabled: boolean;
  summary_model: string;
  research_model: string;
  updated_at?: string;
}

export async function getSettings(): Promise<Settings> {
  const r = await fetch("/api/settings");
  if (!r.ok) throw new Error("settings load failed");
  return r.json();
}

export async function putSettings(s: Settings): Promise<Settings> {
  const r = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(s),
  });
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}));
    throw { status: r.status, errors: detail.detail ?? detail };
  }
  return r.json();
}

export async function runCollect(): Promise<{ scraped: number; inserted: number }> {
  const r = await fetch("/api/collect/run", { method: "POST" });
  if (!r.ok) throw new Error("collect run failed");
  return r.json();
}

export async function runWorker(): Promise<{ claimed: number; done: number; failed: number; skipped_tick: boolean }> {
  const r = await fetch("/api/collect/worker/run", { method: "POST" });
  if (!r.ok) throw new Error("worker run failed");
  return r.json();
}

export async function runNotify(): Promise<{ picked: number; sent: number; skipped: number }> {
  const r = await fetch("/api/notify/run", { method: "POST" });
  if (!r.ok) throw new Error("notify run failed");
  return r.json();
}
