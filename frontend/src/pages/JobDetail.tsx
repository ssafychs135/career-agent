import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getJob, type JobDetailResponse } from "../api";
import { ResearchPanel } from "../ResearchPanel";

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
        companyResearch={data.companyResearch as any}
        jobResearch={data.jobResearch as any}
        refetch={() => getJob(source!, jobId!) as any}
      />
    </main>
  );
}
