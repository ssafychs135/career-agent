import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { getJob, type JobDetailResponse } from "../api";
import { ResearchPanel } from "../ResearchPanel";
import { SPRING_UI } from "../design/springs";
import { careerLabel } from "../career";

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
      className="doc"
      key={`${source}/${jobId}`}
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={SPRING_UI}
    >
      <h1 data-testid="job-title">{job.title}</h1>
      <div className="company" data-testid="job-company">
        {job.company}
      </div>
      {job.locations && <div className="sub">{job.locations}</div>}
      {(job.min_career != null || job.max_career != null) && (
        <div className="sub">모집 연차 · {careerLabel(job.min_career, job.max_career)}</div>
      )}
      {/* 출처는 원문보기 링크에만 표시(별도 수집 뱃지 제거) */}
      {job.url && (
        <a className="origin" href={job.url} target="_blank" rel="noreferrer">
          {siteName(source)}에서 원문 보기 ↗
        </a>
      )}

      {job.summary && (
        <div className="lead-wrap">
          <div className="eyebrow-sm">요약</div>
          {/* 요약의 1·2·3 줄바꿈(\n) 보존 */}
          <div className="lead">{job.summary}</div>
        </div>
      )}

      <ResearchPanel
        source={source}
        jobId={jobId}
        company={job.company}
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
