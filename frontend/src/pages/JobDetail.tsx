import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getJob, type JobDetailResponse } from "../api";
import { ResearchPanel } from "../ResearchPanel";

// api.ts의 research 응답(overview/stability/tech_detail/role_detail 등이 섞인 union,
// sources: unknown)을 ResearchPanel이 기대하는 Research 형태로 변환.
type ApiResearch = {
  overview?: string | null;
  stability?: string | null;
  tech_detail?: string | null;
  role_detail?: string | null;
  status?: string | null;
  sources?: unknown;
};

function adaptResearch(r: ApiResearch | null) {
  if (r === null) return null;
  return {
    overview: r.overview ?? undefined,
    stability: r.stability ?? undefined,
    tech_detail: r.tech_detail ?? undefined,
    role_detail: r.role_detail ?? undefined,
    status: r.status ?? undefined,
    sources: Array.isArray(r.sources) ? (r.sources as string[]) : undefined,
  };
}

export default function JobDetail() {
  const { source, jobId } = useParams();
  const [data, setData] = useState<JobDetailResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!source || !jobId) return;
    getJob(source, jobId)
      .then(setData)
      .catch(() => setError("공고를 찾을 수 없습니다"));
  }, [source, jobId]);

  if (error) {
    return (
      <main style={{ padding: 24, fontFamily: "sans-serif" }}>
        <p role="alert">{error}</p>
        <Link to="/jobs">← 목록</Link>
      </main>
    );
  }
  if (!data) {
    return <main style={{ padding: 24, fontFamily: "sans-serif" }}>불러오는 중…</main>;
  }

  const { job } = data;

  return (
    <main style={{ padding: 24, fontFamily: "sans-serif" }}>
      <Link to="/jobs">← 목록</Link>
      <h1 data-testid="job-title">{job.title}</h1>
      <p data-testid="job-company">{job.company}</p>
      <p>
        {job.locations} · {job.status}
      </p>
      {job.summary && <p>{job.summary}</p>}
      {job.url && (
        <p>
          <a href={job.url} target="_blank" rel="noreferrer">
            원문 보기
          </a>
        </p>
      )}
      <ResearchPanel
        source={source!}
        jobId={jobId!}
        companyResearch={adaptResearch(data.companyResearch)}
        jobResearch={adaptResearch(data.jobResearch)}
        refetch={async () => {
          const d = await getJob(source!, jobId!);
          return {
            companyResearch: adaptResearch(d.companyResearch),
            jobResearch: adaptResearch(d.jobResearch),
          };
        }}
      />
    </main>
  );
}
