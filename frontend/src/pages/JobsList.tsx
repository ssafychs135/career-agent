import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { motion } from "motion/react";
import { getJobs, type JobSummary } from "../api";
import { stagger } from "../design/springs";

const LIMIT = 20;
const DEBOUNCE_MS = 250;
const EMPTY = { status: "", source: "", location: "", tech: "", keyword: "" };
type Filters = typeof EMPTY;

/** Free-text filters (open-ended values → live text, not a dropdown). */
const TEXT_FILTERS: { key: keyof Filters; label: string; testid: string; grow?: boolean }[] = [
  { key: "keyword", label: "제목·회사·요약 검색", testid: "filter-keyword", grow: true },
  { key: "location", label: "지역", testid: "filter-location" },
  { key: "tech", label: "기술", testid: "filter-tech" },
];

export default function JobsList() {
  const [filters, setFilters] = useState<Filters>(EMPTY);
  const [offset, setOffset] = useState(0);
  const [items, setItems] = useState<JobSummary[]>([]);
  const [total, setTotal] = useState(0);
  const [error, setError] = useState("");
  // Dropdown options accumulate from real results — always match the data, no extra query.
  const [statusOpts, setStatusOpts] = useState<string[]>([]);
  const [sourceOpts, setSourceOpts] = useState<string[]>([]);
  const first = useRef(true);

  const load = useCallback((f: Filters, off: number) => {
    const params: Record<string, string | number> = { limit: LIMIT, offset: off };
    for (const [k, v] of Object.entries(f)) if (v) params[k] = v;
    getJobs(params)
      .then((p) => {
        setItems(p.items);
        setTotal(p.total);
        setError("");
        setStatusOpts((prev) => union(prev, p.items.map((j) => j.status)));
        setSourceOpts((prev) => union(prev, p.items.map((j) => j.source)));
      })
      .catch(() => setError("불러오기 실패"));
  }, []);

  // Live filtering — reload whenever a filter or the page changes (§1 response).
  // Text typing is debounced; the first load fires immediately.
  useEffect(() => {
    if (first.current) {
      first.current = false;
      load(filters, offset);
      return;
    }
    const t = setTimeout(() => load(filters, offset), DEBOUNCE_MS);
    return () => clearTimeout(t);
  }, [filters, offset, load]);

  // Any filter change returns to page 1.
  const setFilter = (k: keyof Filters, v: string) => {
    setOffset(0);
    setFilters((f) => ({ ...f, [k]: v }));
  };

  const page = Math.floor(offset / LIMIT) + 1;
  const pages = Math.max(1, Math.ceil(total / LIMIT));

  return (
    <main style={{ maxWidth: 960, margin: "0 auto", padding: "var(--sp-6) clamp(1rem, 4vw, 2rem)" }}>
      <h1 style={{ marginBottom: "var(--sp-5)" }}>공고</h1>

      {/* Translucent filter toolbar — changes apply live, no submit (§1) */}
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
        <input
          data-testid="filter-keyword"
          placeholder="제목·회사·요약 검색"
          value={filters.keyword}
          onChange={(e) => setFilter("keyword", e.target.value)}
          style={{ flex: "1 1 240px", minWidth: 0 }}
        />
        <select
          data-testid="filter-source"
          value={filters.source}
          onChange={(e) => setFilter("source", e.target.value)}
          aria-label="소스"
        >
          <option value="">소스 전체</option>
          {sourceOpts.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <select
          data-testid="filter-status"
          value={filters.status}
          onChange={(e) => setFilter("status", e.target.value)}
          aria-label="상태"
        >
          <option value="">상태 전체</option>
          {statusOpts.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        {TEXT_FILTERS.filter((f) => f.key === "location" || f.key === "tech").map((f) => (
          <input
            key={f.testid}
            data-testid={f.testid}
            placeholder={f.label}
            value={filters[f.key]}
            onChange={(e) => setFilter(f.key, e.target.value)}
            style={{ flex: "0 1 130px", minWidth: 0 }}
          />
        ))}
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
              style={{ display: "block", textDecoration: "none", color: "inherit" }}
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

/** Merge new non-empty string values into a sorted distinct option list. */
function union(prev: string[], next: (string | null)[]): string[] {
  const set = new Set(prev);
  for (const v of next) if (v) set.add(v);
  return [...set].sort();
}
