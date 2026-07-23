import { useEffect, useMemo, useState } from "react";
import { motion } from "motion/react";
import { getSettings, putSettings, type Settings as S } from "../settingsApi";
import { getFacets, type Facets } from "../filtersApi";
import { SPRING_UI, stagger } from "../design/springs";

/** 전역 필터 — 지역은 허용목록(체크한 지역만 표시), 기업은 숨김목록(해제하면 숨김). */
export default function Filters() {
  const [form, setForm] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [facets, setFacets] = useState<Facets | null>(null);
  const [busy, setBusy] = useState(false);
  const [q, setQ] = useState("");
  const [hiddenFirst, setHiddenFirst] = useState(false);

  useEffect(() => { getSettings().then((s) => { setForm(s); setSaved(s); }); }, []);
  useEffect(() => { getFacets().then(setFacets).catch(() => { /* keep empty */ }); }, []);

  const dirty = !!form && !!saved && JSON.stringify(form) !== JSON.stringify(saved);

  async function save() {
    if (!form) return;
    setBusy(true);
    try {
      // 이 페이지는 전역 필터 두 필드만 소유한다. PUT은 전체 문서를 덮어쓰므로,
      // 마운트 시점 스냅샷을 그대로 쓰면 그 사이 Ops에서 바뀐 설정(enabled 등)을 되돌린다.
      const fresh = await getSettings();
      const r = await putSettings({
        ...fresh,
        allowed_regions: form.allowed_regions,
        hidden_companies: form.hidden_companies,
      });
      setForm(r);
      setSaved(r);
    } finally {
      setBusy(false);
    }
  }

  const toggleRegion = (name: string) =>
    form && setForm({
      ...form,
      allowed_regions: form.allowed_regions.includes(name)
        ? form.allowed_regions.filter((r) => r !== name)
        : [...form.allowed_regions, name],
    });

  // 체크 = 표시, 해제 = 숨김. 그래서 토글은 hidden_companies에 넣고 빼는 것.
  const toggleCompany = (name: string) =>
    form && setForm({
      ...form,
      hidden_companies: form.hidden_companies.includes(name)
        ? form.hidden_companies.filter((c) => c !== name)
        : [...form.hidden_companies, name],
    });

  const companies = useMemo(() => {
    if (!facets || !form) return [];
    const hidden = new Set(form.hidden_companies);
    const needle = q.trim().toLowerCase();
    const list = facets.companies.filter((c) => c.name.toLowerCase().includes(needle));
    // sort는 안정 정렬 — 백엔드가 준 공고수 내림차순이 그룹 안에서 유지된다.
    return hiddenFirst
      ? [...list].sort((a, b) => Number(hidden.has(b.name)) - Number(hidden.has(a.name)))
      : list;
  }, [facets, form, q, hiddenFirst]);

  const card = (i: number) => ({
    className: "card",
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: stagger(i),
  });

  return (
    <main className="page">
      <motion.div className="page-head"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={SPRING_UI}>
        <div>
          <h1>전역 필터</h1>
          <p className="sub">공고 목록에 나오기 전에 걸립니다. 숨김은 삭제가 아니라 언제든 되돌릴 수 있습니다.</p>
        </div>
        <button className="btn-primary" onClick={save} disabled={!dirty || busy}>저장</button>
      </motion.div>

      <motion.section {...card(1)}>
        <div className="card-h">지역 · 체크한 지역만 표시</div>
        {!form || !facets ? (
          <p className="caption" style={{ margin: 0 }}>불러오는 중…</p>
        ) : (
          <>
            <p className="caption" style={{ marginTop: 0 }}>
              {form.allowed_regions.length === 0
                ? "선택 없음 — 전체 지역을 표시합니다."
                : `${form.allowed_regions.length}개 지역만 표시 중`}
            </p>
            <div className="chk-grid">
              {facets.regions.map((r) => (
                <label className="chk" key={r.name}>
                  <input type="checkbox" aria-label={`${r.name} (${r.count})`}
                    checked={form.allowed_regions.includes(r.name)}
                    onChange={() => toggleRegion(r.name)} />
                  <span>{r.name}</span>
                  <span className="chk-n">{r.count}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </motion.section>

      <motion.section {...card(2)}>
        <div className="card-h">기업 · 체크 해제하면 숨김</div>
        {!form || !facets ? (
          <p className="caption" style={{ margin: 0 }}>불러오는 중…</p>
        ) : (
          <>
            <div className="run-bar">
              <input className="control" type="search" aria-label="기업 검색" placeholder="기업 검색"
                value={q} onChange={(e) => setQ(e.target.value)} />
              <label className="chk">
                <input type="checkbox" aria-label="숨긴 기업 먼저 보기"
                  checked={hiddenFirst} onChange={(e) => setHiddenFirst(e.target.checked)} />
                <span>숨긴 기업 먼저</span>
              </label>
              <span className="caption">
                {facets.companies.length}개 중 {form.hidden_companies.length}개 숨김
              </span>
            </div>
            <div className="chk-list">
              {companies.map((c) => (
                <label className="chk" key={c.name}>
                  <input type="checkbox" aria-label={`${c.name} (${c.count})`}
                    checked={!form.hidden_companies.includes(c.name)}
                    onChange={() => toggleCompany(c.name)} />
                  <span>{c.name}</span>
                  <span className="chk-n">{c.count}</span>
                </label>
              ))}
            </div>
          </>
        )}
      </motion.section>
    </main>
  );
}
