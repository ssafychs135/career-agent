import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { getJobs, type JobSummary } from "../api";
import { SPRING_UI, stagger } from "../design/springs";

const LIMIT = 20;
const EMPTY = { status: "", source: "", location: "", tech: "", keyword: "" };
type Filters = typeof EMPTY;

const FILTERS: { key: keyof Filters; label: string; testid: string; grow?: boolean }[] = [
  { key: "keyword", label: "제목·회사·요약 검색", testid: "filter-keyword", grow: true },
  { key: "status", label: "상태", testid: "filter-status" },
  { key: "source", label: "소스", testid: "filter-source" },
  { key: "location", label: "지역", testid: "filter-location" },
  { key: "tech", label: "기술", testid: "filter-tech" },
];

export default function JobsList() {
  const [form, setForm] = useState<Filters>(EMPTY);
  const [applied, setApplied] = useState<Filters>(EMPTY);
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
  const onKey = (e: React.KeyboardEvent) => {
    if (e.key === "Enter") onSearch();
  };

  const page = Math.floor(offset / LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "var(--sp-6) clamp(1rem, 4vw, 2rem)" }}>
      <h1 style={{ marginBottom: "var(--sp-5)" }}>공고</h1>

      {/* Translucent filter toolbar — a light material for interactive controls (§12) */}
      <div
        className="card"
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: "var(--sp-2)",
          padding: "var(--sp-3)",
          marginBottom: "var(--sp-4)",
        }}
      >
        {FILTERS.map((f) => (
          <input
            key={f.testid}
            data-testid={f.testid}
            placeholder={f.label}
            value={form[f.key]}
            onChange={set(f.key)}
            onKeyDown={onKey}
            style={{ flex: f.grow ? "1 1 240px" : "0 1 130px", minWidth: 0 }}
          />
        ))}
        <button data-testid="search-btn" className="btn-primary" onClick={onSearch}>
          검색
        </button>
      </div>

      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: "var(--sp-3)",
        }}
      >
        <p data-testid="job-total" className="caption" style={{ margin: 0 }}>
          총 {total.toLocaleString()}건
        </p>
        {error && (
          <span role="alert" className="pill pill-bad">
            {error}
          </span>
        )}
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: "var(--sp-2)" }}>
        {items.map((j, i) => (
          <motion.div
            key={`${j.source}:${j.job_id}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={stagger(i)}
            whileHover={{ y: -2 }}
          >
            <Link
              data-testid="job-link"
              to={`/jobs/${j.source}/${j.job_id}`}
              style={{
                display: "block",
                textDecoration: "none",
                color: "inherit",
              }}
              className="card"
            >
              <div
                style={{
                  padding: "var(--sp-4)",
                  display: "flex",
                  gap: "var(--sp-3)",
                  alignItems: "flex-start",
                }}
              >
                <div style={{ flex: 1, minWidth: 0 }}>
                  <div className="caption" style={{ marginBottom: 2 }}>
                    {j.company}
                  </div>
                  <div style={{ fontWeight: 600, letterSpacing: "-0.01em" }}>{j.title}</div>
                  <div className="caption" style={{ marginTop: 4 }}>
                    {j.locations}
                  </div>
                </div>
                <div
                  style={{
                    display: "flex",
                    flexDirection: "column",
                    alignItems: "flex-end",
                    gap: 6,
                  }}
                >
                  {j.status && <span className="pill">{j.status}</span>}
                  <div style={{ display: "flex", gap: 4 }}>
                    {j.has_company_research && <span className="pill pill-accent">기업</span>}
                    {j.has_job_research && <span className="pill pill-accent">공고</span>}
                  </div>
                </div>
              </div>
            </Link>
          </motion.div>
        ))}
      </div>

      {/* Pagination — inherits the global :active press feedback (§1) */}
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "center",
          gap: "var(--sp-3)",
          marginTop: "var(--sp-5)",
        }}
      >
        <button
          data-testid="prev-btn"
          disabled={offset === 0}
          onClick={() => setOffset(Math.max(0, offset - LIMIT))}
        >
          이전
        </button>
        <span className="caption">
          {page} / {pages}
        </span>
        <button
          data-testid="next-btn"
          disabled={offset + LIMIT >= total}
          onClick={() => setOffset(offset + LIMIT)}
        >
          다음
        </button>
      </div>
    </main>
  );
}
