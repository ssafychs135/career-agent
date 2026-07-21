import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { motion } from "motion/react";
import { getJob, type JobDetailResponse } from "../api";
import { ResearchPanel } from "../ResearchPanel";
import { SPRING_UI } from "../design/springs";

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

const wrap: React.CSSProperties = {
  maxWidth: 760,
  margin: "0 auto",
  padding: "var(--sp-5) clamp(1rem, 4vw, 2rem) var(--sp-8)",
};

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
      <main style={wrap}>
        <Link to="/jobs" className="caption">
          ← 목록
        </Link>
        <p role="alert" className="pill pill-bad" style={{ marginTop: "var(--sp-4)" }}>
          {error}
        </p>
      </main>
    );
  }
  if (!data) {
    return (
      <main style={wrap}>
        <p className="caption">불러오는 중…</p>
      </main>
    );
  }

  const { job } = data;

  return (
    <main style={wrap}>
      <Link to="/jobs" className="caption">
        ← 목록
      </Link>

      <motion.header
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={SPRING_UI}
        style={{ margin: "var(--sp-3) 0 var(--sp-5)" }}
      >
        <div className="caption" data-testid="job-company" style={{ marginBottom: 4 }}>
          {job.company}
        </div>
        <h1 data-testid="job-title">{job.title}</h1>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            gap: 8,
            alignItems: "center",
            marginTop: "var(--sp-3)",
          }}
        >
          {job.locations && <span className="pill">{job.locations}</span>}
          {job.status && <span className="pill">{job.status}</span>}
          {job.url && (
            <a href={job.url} target="_blank" rel="noreferrer" style={{ fontSize: "0.85rem" }}>
              원문 보기 ↗
            </a>
          )}
        </div>
      </motion.header>

      {job.summary && (
        <motion.p
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ ...SPRING_UI, delay: 0.05 }}
          style={{ color: "var(--text-2)", lineHeight: 1.6, marginBottom: "var(--sp-5)" }}
        >
          {job.summary}
        </motion.p>
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
