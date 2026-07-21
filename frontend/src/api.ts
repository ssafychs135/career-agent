export async function getHealth(): Promise<{ status: string }> {
  const r = await fetch("/api/health");
  if (!r.ok) throw new Error("health failed");
  return r.json();
}

export async function getClaudeCheck(): Promise<{ ok: boolean; reply: string }> {
  const r = await fetch("/api/claude-check");
  if (!r.ok) throw new Error("claude-check failed");
  return r.json();
}

export interface JobSummary {
  source: string;
  job_id: string;
  company: string | null;
  title: string | null;
  url: string | null;
  locations: string | null;
  min_career: number | null;
  max_career: number | null;
  status: string | null;
  collected_at: string | null;
  tech_stacks: string[] | string | null;
  has_company_research: boolean;
  has_job_research: boolean;
}

export interface JobsPage {
  items: JobSummary[];
  total: number;
  limit: number;
  offset: number;
}

export interface Job {
  source: string;
  job_id: string;
  company: string | null;
  title: string | null;
  url: string | null;
  locations: string | null;
  min_career: number | null;
  max_career: number | null;
  tech_stacks: string[] | string | null;
  summary: string | null;
  status: string | null;
  attempts: number | null;
  collected_at: string | null;
  updated_at: string | null;
  closed_at: string | null;
}

export interface CompanyResearch {
  overview: string | null;
  stability: string | null;
  sources: unknown;
  status: string;
  researched_at: string | null;
}

export interface JobResearch {
  tech_detail: string | null;
  role_detail: string | null;
  sources: unknown;
  status: string;
  researched_at: string | null;
}

export interface JobDetailResponse {
  job: Job;
  companyResearch: CompanyResearch | null;
  jobResearch: JobResearch | null;
}

export type JobsFilters = Record<string, string | number>;

export async function getJobs(params: JobsFilters = {}): Promise<JobsPage> {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== "" && v != null) qs.set(k, String(v));
  }
  const r = await fetch(`/api/jobs?${qs.toString()}`);
  if (!r.ok) throw new Error("jobs 조회 실패");
  return r.json();
}

export async function getJob(source: string, jobId: string): Promise<JobDetailResponse> {
  const r = await fetch(`/api/jobs/${encodeURIComponent(source)}/${encodeURIComponent(jobId)}`);
  if (!r.ok) throw new Error("공고 조회 실패");
  return r.json();
}
