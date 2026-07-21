import { useEffect, useState } from "react";
import { useParams, Link } from "react-router-dom";
import { getJob, type JobDetailResponse } from "../api";

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

  const { job, companyResearch, jobResearch } = data;

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
      <h2>리서치</h2>
      <ul>
        <li data-testid="research-company">기업 리서치: {companyResearch ? "있음" : "없음"}</li>
        <li data-testid="research-job">공고 리서치: {jobResearch ? "있음" : "없음"}</li>
      </ul>
    </main>
  );
}
