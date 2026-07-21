import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { getJobs, type JobSummary } from "../api";

const LIMIT = 20;
const EMPTY = { status: "", source: "", location: "", tech: "", keyword: "" };
type Filters = typeof EMPTY;

export default function JobsList() {
  const [form, setForm] = useState<Filters>(EMPTY);       // 입력 중 값
  const [applied, setApplied] = useState<Filters>(EMPTY); // 확정된 필터
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");

  const load = useCallback(() => {
    const params: Record<string, string | number> = { limit: LIMIT, offset };
    for (const [k, v] of Object.entries(applied)) if (v) params[k] = v;
    getJobs(params)
      .then((p) => {
        setItems(p.items);
        setTotal(p.total);
        setError("");
      })
      .catch(() => setError("불러오기 실패"));
  }, [applied, offset]);

  useEffect(() => {
    load();
  }, [load]);

  const onSearch = () => {
    setOffset(0);
    setApplied(form);
  };
  const set = (k: keyof Filters) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setForm({ ...form, [k]: e.target.value });

  return (
    <main style={{ padding: 24, fontFamily: "sans-serif" }}>
      <h1>공고</h1>
      <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
        <input data-testid="filter-status" placeholder="상태" value={form.status} onChange={set("status")} />
        <input data-testid="filter-source" placeholder="소스" value={form.source} onChange={set("source")} />
        <input data-testid="filter-location" placeholder="지역" value={form.location} onChange={set("location")} />
        <input data-testid="filter-tech" placeholder="기술" value={form.tech} onChange={set("tech")} />
        <input data-testid="filter-keyword" placeholder="키워드" value={form.keyword} onChange={set("keyword")} />
        <button data-testid="search-btn" onClick={onSearch}>검색</button>
      </div>
      {error && <p role="alert">{error}</p>}
      <p data-testid="job-total">총 {total}건</p>
      <table style={{ borderCollapse: "collapse", width: "100%" }}>
        <thead>
          <tr>
            <th style={{ textAlign: "left" }}>회사</th>
            <th style={{ textAlign: "left" }}>제목</th>
            <th style={{ textAlign: "left" }}>지역</th>
            <th style={{ textAlign: "left" }}>상태</th>
            <th style={{ textAlign: "left" }}>리서치</th>
          </tr>
        </thead>
        <tbody>
          {items.map((j) => (
            <tr key={`${j.source}:${j.job_id}`}>
              <td>{j.company}</td>
              <td>
                <Link data-testid="job-link" to={`/jobs/${j.source}/${j.job_id}`}>
                  {j.title}
                </Link>
              </td>
              <td>{j.locations}</td>
              <td>{j.status}</td>
              <td>
                {j.has_company_research ? "기업" : "-"} / {j.has_job_research ? "공고" : "-"}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ marginTop: 12 }}>
        <button data-testid="prev-btn" disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - LIMIT))}>
          이전
        </button>
        <span style={{ margin: "0 8px" }}>{Math.floor(offset / LIMIT) + 1}</span>
        <button data-testid="next-btn" disabled={offset + LIMIT >= total} onClick={() => setOffset(offset + LIMIT)}>
          다음
        </button>
      </div>
    </main>
  );
}
