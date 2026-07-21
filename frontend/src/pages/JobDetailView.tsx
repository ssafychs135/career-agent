import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { getJob, type JobDetailResponse } from "../api";
import { ResearchPanel } from "../ResearchPanel";
import { SPRING_UI } from "../design/springs";

// api.ts research union(overview/stability/tech_detail/role_detail, sources: unknown)을
// ResearchPanel이 기대하는 Research 형태로 변환.
type ApiResearch = {
  overview?: string | null;
  stability?: string | null;
  tech_detail?: string | null;
  role_detail?: string | null;
  status?: string | null;
  sources?: unknown;
};

// 수집 출처(source) → 사람이 읽는 사이트명.
const SITE_NAMES: Record<string, string> = {
  wanted: "원티드",
  saramin: "사람인",
  jumpit: "점핏",
  "jump-it": "점핏",
  jobkorea: "잡코리아",
  rocketpunch: "로켓펀치",
  programmers: "프로그래머스",
  linkedin: "LinkedIn",
};
const siteName = (s: string) => SITE_NAMES[s.toLowerCase()] ?? s;

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

/** 선택된 공고의 내용 + 분석(리서치). 탐색기 3번째 패널이 소비한다. */
export default function JobDetailView({ source, jobId }: { source: string; jobId: string }) {
  const [data, setData] = useState<JobDetailResponse | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    setData(null);
    setError("");
    getJob(source, jobId)
      .then(setData)
      .catch(() => setError("공고를 찾을 수 없습니다"));
  }, [source, jobId]);

  if (error) {
    return (
      <p role="alert" className="pill pill-bad" style={{ margin: "var(--sp-4)" }}>
        {error}
      </p>
    );
  }
  if (!data) {
    return <p className="caption" style={{ margin: "var(--sp-5)" }}>불러오는 중…</p>;
  }

  const { job } = data;

  return (
    <motion.article
      key={`${source}/${jobId}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={SPRING_UI}
    >
      <div className="caption" data-testid="job-company" style={{ marginBottom: 4 }}>
        {job.company}
      </div>
      <h1
        data-testid="job-title"
        style={{
          fontSize: "clamp(2rem, 1.3rem + 2.4vw, 3rem)",
          lineHeight: 1.05,
          letterSpacing: "-0.03em",
        }}
      >
        {job.title}
      </h1>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 8,
          alignItems: "center",
          margin: "var(--sp-3) 0 var(--sp-5)",
        }}
      >
        {job.locations && <span className="pill">{job.locations}</span>}
        {job.status && <span className="pill">{job.status}</span>}
        {/* 어느 사이트에서 수집된 공고인지 명시 */}
        <span className="pill pill-accent">수집: {siteName(source)}</span>
        {job.url && (
          <a href={job.url} target="_blank" rel="noreferrer" style={{ fontSize: "0.9rem", fontWeight: 500 }}>
            {siteName(source)}에서 원문 보기 ↗
          </a>
        )}
      </div>

      {job.summary && (
        <p style={{ color: "var(--text-2)", lineHeight: 1.65, maxWidth: "64ch", marginBottom: "var(--sp-5)" }}>
          {job.summary}
        </p>
      )}

      <ResearchPanel
        source={source}
        jobId={jobId}
        companyResearch={adaptResearch(data.companyResearch)}
        jobResearch={adaptResearch(data.jobResearch)}
        refetch={async () => {
          const d = await getJob(source, jobId);
          return {
            companyResearch: adaptResearch(d.companyResearch),
            jobResearch: adaptResearch(d.jobResearch),
          };
        }}
      />
    </motion.article>
  );
}
