import { useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { getJobs, type JobSummary } from "../api";
import JobDetailView from "./JobDetailView";

const PAGE = 100; // /api/jobs limit cap

/** 시/도 단위 지역 토큰. "서울 강남구"→"서울", "서울, 부산"→["서울","부산"]. */
function regionsOf(loc: string | null): string[] {
  if (!loc) return [];
  return loc
    .split(",")
    .map((p) => p.trim().split(/\s+/)[0])
    .filter(Boolean);
}

type Company = { name: string; count: number; regions: string[]; hasResearch: boolean };

export default function Explorer() {
  const { source, jobId } = useParams();
  const navigate = useNavigate();

  const [jobs, setJobs] = useState<JobSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const [companyQuery, setCompanyQuery] = useState("");
  const [region, setRegion] = useState("");
  // 다중 선택: 여러 기업을 고르면 그 기업들의 공고가 2계층에 합쳐진다.
  const [selected, setSelected] = useState<Set<string>>(new Set());

  // 전체 공고를 한 번에 확보(현재 규모 수백 건 — 프론트에서 기업/지역 파생).
  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const all: JobSummary[] = [];
        for (let off = 0; off < 5000; off += PAGE) {
          const p = await getJobs({ limit: PAGE, offset: off });
          all.push(...p.items);
          if (all.length >= p.total || p.items.length === 0) break;
        }
        if (!cancelled) {
          setJobs(all);
          setLoaded(true);
        }
      } catch {
        if (!cancelled) setError("불러오기 실패");
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  const companies = useMemo<Company[]>(() => {
    const map = new Map<string, Company>();
    for (const j of jobs) {
      const name = j.company?.trim();
      if (!name) continue;
      let c = map.get(name);
      if (!c) {
        c = { name, count: 0, regions: [], hasResearch: false };
        map.set(name, c);
      }
      c.count++;
      c.hasResearch = c.hasResearch || !!j.has_company_research;
      for (const r of regionsOf(j.locations)) if (!c.regions.includes(r)) c.regions.push(r);
    }
    // 기업명(가나다) 순 정렬.
    return [...map.values()].sort((a, b) => a.name.localeCompare(b.name, "ko"));
  }, [jobs]);

  const regionOpts = useMemo(() => {
    const s = new Set<string>();
    for (const c of companies) for (const r of c.regions) s.add(r);
    return [...s].sort((a, b) => a.localeCompare(b, "ko"));
  }, [companies]);

  const visibleCompanies = useMemo(() => {
    const q = companyQuery.trim().toLowerCase();
    return companies.filter(
      (c) => (!q || c.name.toLowerCase().includes(q)) && (!region || c.regions.includes(region)),
    );
  }, [companies, companyQuery, region]);

  // 딥링크(/jobs/:source/:jobId)로 진입 시 해당 공고의 기업을 선택 집합에 추가.
  useEffect(() => {
    if (!loaded || !source || !jobId) return;
    const j = jobs.find((x) => x.source === source && x.job_id === jobId);
    const name = j?.company?.trim();
    if (name) setSelected((prev) => (prev.has(name) ? prev : new Set(prev).add(name)));
  }, [loaded, source, jobId, jobs]);

  // 클릭 토글(다중 선택).
  const toggleCompany = (name: string) =>
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name);
      else next.add(name);
      return next;
    });

  // 선택된 모든 기업의 공고를 합쳐 기업명→제목 순으로 정렬.
  const companyJobs = useMemo(() => {
    if (selected.size === 0) return [];
    return jobs
      .filter(
        (j) => selected.has(j.company?.trim() ?? "") && (!region || regionsOf(j.locations).includes(region)),
      )
      .sort(
        (a, b) =>
          (a.company ?? "").localeCompare(b.company ?? "", "ko") ||
          (a.title ?? "").localeCompare(b.title ?? "", "ko"),
      );
  }, [jobs, selected, region]);

  const selCount = selected.size;
  const selNames = [...selected].sort((a, b) => a.localeCompare(b, "ko"));

  // 좁은 화면 단일-패널 드릴다운.
  const mobilePane = source && jobId ? "detail" : selCount > 0 ? "jobs" : "companies";

  return (
    <div className="explorer" data-mobile={mobilePane}>
      {/* 1) 기업 — 기업명·지역 필터, 여러 개 선택 가능 */}
      <div className="col col-companies">
        <div className="col-head">
          <div className="row" style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
            <h2 style={{ fontSize: "1.05rem" }}>기업</h2>
            {selCount > 0 && (
              <button className="linklike" onClick={() => setSelected(new Set())}>
                {selCount}개 해제
              </button>
            )}
          </div>
          <div className="col-filters">
            <input
              data-testid="filter-company"
              placeholder="기업명 검색"
              value={companyQuery}
              onChange={(e) => setCompanyQuery(e.target.value)}
            />
            <select
              data-testid="filter-region"
              aria-label="지역"
              value={region}
              onChange={(e) => setRegion(e.target.value)}
            >
              <option value="">지역 전체</option>
              {regionOpts.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          </div>
        </div>
        <div className="col-list">
          {error && (
            <span role="alert" className="pill pill-bad">
              {error}
            </span>
          )}
          {!loaded && !error && <span className="caption">불러오는 중…</span>}
          {loaded && !error && visibleCompanies.length === 0 && (
            <span className="caption">기업이 없습니다</span>
          )}
          {visibleCompanies.map((c) => {
            const on = selected.has(c.name);
            return (
              <button
                key={c.name}
                className={`item${on ? " on" : ""}`}
                aria-pressed={on}
                onClick={() => toggleCompany(c.name)}
              >
                <div className="row">
                  <span className="name">{c.name}</span>
                  {on ? (
                    <span className="pill pill-solid">✓ 선택됨</span>
                  ) : (
                    c.hasResearch && <span className="pill">기업 리서치</span>
                  )}
                </div>
                <div className="caption" style={{ marginTop: 2 }}>
                  {c.regions.slice(0, 2).join("·")} · 공고 {c.count}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 2) 공고 — 선택된 기업들의 공고를 합쳐서 표시 */}
      <div className="col col-jobs">
        <div className="col-head">
          <button className="mobile-back" onClick={() => setSelected(new Set())} style={{ marginBottom: 8 }}>
            ← 기업
          </button>
          {selCount > 0 ? (
            <>
              <div className="caption" style={{ marginBottom: 2 }}>공고</div>
              <h2 style={{ fontSize: "1.15rem" }}>
                {selCount === 1 ? selNames[0] : `선택한 기업 ${selCount}곳`}
              </h2>
              <div className="caption" style={{ marginTop: 4 }}>
                {selCount > 1 ? selNames.slice(0, 3).join(", ") + (selCount > 3 ? " 외" : "") + " · " : ""}
                {region ? region + " · " : ""}공고 {companyJobs.length}건
              </div>
            </>
          ) : (
            <>
              <h2 style={{ fontSize: "1.05rem" }}>공고</h2>
              <div className="caption" style={{ marginTop: 6 }}>← 기업을 선택하세요 (여러 곳 선택 가능)</div>
            </>
          )}
        </div>
        <div className="col-list">
          {companyJobs.map((j) => {
            const on = j.source === source && j.job_id === jobId;
            return (
              <button
                key={`${j.source}:${j.job_id}`}
                data-testid="job-link"
                className={`item${on ? " on" : ""}`}
                aria-current={on ? "true" : undefined}
                onClick={() => navigate(`/jobs/${j.source}/${j.job_id}`)}
              >
                {/* 여러 기업이 섞이므로 각 공고에 기업명 표기 */}
                {selCount > 1 && (
                  <div className="caption" style={{ marginBottom: 2 }}>
                    {j.company}
                  </div>
                )}
                <div className="name">{j.title}</div>
                <div className="row" style={{ marginTop: 6 }}>
                  <span className="caption">{j.locations}</span>
                  <span style={{ display: "flex", gap: 4 }}>
                    {j.status && <span className="pill">{j.status}</span>}
                    {j.has_job_research && <span className="pill">분석✓</span>}
                  </span>
                </div>
              </button>
            );
          })}
        </div>
      </div>

      {/* 3) 공고 내용 · 분석 */}
      <div className="detail-pane">
        {source && jobId ? (
          <>
            <button className="mobile-back" onClick={() => navigate("/jobs")} style={{ marginBottom: 16 }}>
              ← 공고
            </button>
            <JobDetailView source={source} jobId={jobId} />
          </>
        ) : (
          <div className="caption" style={{ margin: "var(--sp-6)" }}>
            기업을 선택하고 공고를 고르면 내용과 분석이 여기에 표시됩니다.
          </div>
        )}
      </div>
    </div>
  );
}
