import { useEffect, useState } from "react";
import { getSettings, putSettings, runCollect, runWorker, type Settings as S } from "../settingsApi";
import ChipInput from "../components/ChipInput";
import Segmented from "../components/Segmented";

export default function Settings() {
  const [form, setForm] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [busy, setBusy] = useState(false);
  const [runMsg, setRunMsg] = useState("");

  useEffect(() => {
    getSettings().then((s) => { setForm(s); setSaved(s); });
  }, []);

  if (!form || !saved) return <p className="caption" style={{ margin: "var(--sp-5)" }}>불러오는 중…</p>;

  const dirty = JSON.stringify(form) !== JSON.stringify(saved);
  const set = <K extends keyof S>(k: K, v: S[K]) => setForm({ ...form, [k]: v });
  const num = (k: keyof S) => (e: React.ChangeEvent<HTMLInputElement>) => set(k, Number(e.target.value) as never);

  async function save() {
    setBusy(true);
    try { const r = await putSettings(form!); setForm(r); setSaved(r); }
    finally { setBusy(false); }
  }
  async function doRun(fn: () => Promise<Record<string, number | boolean>>, label: string) {
    setBusy(true); setRunMsg("실행 중…");
    try { const r = await fn(); setRunMsg(`${label}: ${JSON.stringify(r)}`); }
    finally { setBusy(false); }
  }

  return (
    <div className="doc" style={{ maxWidth: 640 }}>
      <h1 style={{ display: "flex", justifyContent: "space-between" }}>
        설정
        <button className="btn-primary" onClick={save} disabled={!dirty || busy}>저장</button>
      </h1>

      <section>
        <h2 className="section-title">수집 제어</h2>
        <label className="field">
          <span className="flabel">수집 활성화</span>
          <input type="checkbox" checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
        </label>
        <div style={{ display: "flex", gap: 8, alignItems: "center" }}>
          <button onClick={() => doRun(runCollect, "수집")} disabled={dirty || busy}>지금 수집</button>
          <button onClick={() => doRun(runWorker, "워커")} disabled={dirty || busy}>워커 1회</button>
          <span className="caption">{dirty ? "먼저 저장하세요" : runMsg}</span>
        </div>
      </section>

      <section>
        <h2 className="section-title">수집기</h2>
        <div className="field"><span className="flabel">키워드</span>
          <ChipInput mode="text" value={form.keywords} onChange={(v) => set("keywords", v as string[])} /></div>
        <div className="field"><span className="flabel">원티드 카테고리</span>
          <ChipInput mode="number" value={form.allowed_wanted_categories} onChange={(v) => set("allowed_wanted_categories", v as number[])} /></div>
        <label className="field"><span className="flabel">경력 상한(년)</span>
          <input aria-label="경력 상한" type="number" value={form.max_career_years} onChange={num("max_career_years")} /></label>
        <label className="field"><span className="flabel">페이지 상한</span>
          <input aria-label="페이지 상한" type="number" value={form.max_pages} onChange={num("max_pages")} /></label>
        <label className="field"><span className="flabel">수집 시각(시)</span>
          <input aria-label="수집 시각" type="number" value={form.collect_hour} onChange={num("collect_hour")} />
          <span className="caption">저장 시 즉시 재적용</span></label>
      </section>

      <section>
        <h2 className="section-title">워커</h2>
        <label className="field"><span className="flabel">배치 크기</span>
          <input aria-label="배치 크기" type="number" value={form.batch_size} onChange={num("batch_size")} /></label>
        <label className="field"><span className="flabel">재시도(회)</span>
          <input aria-label="재시도" type="number" value={form.max_attempts} onChange={num("max_attempts")} /></label>
        <label className="field"><span className="flabel">워커 주기(분)</span>
          <input aria-label="워커 주기" type="number" value={form.worker_interval_min} onChange={num("worker_interval_min")} />
          <span className="caption">저장 시 즉시 재적용</span></label>
        <div className="field"><span className="flabel">요약 백엔드</span>
          <Segmented value={form.summary_backend}
            options={[{ label: "로컬 LLM", value: "local" }, { label: "claude", value: "claude" }]}
            onChange={(v) => set("summary_backend", v)} /></div>
        <label className="field"><span className="flabel">모델</span>
          <input aria-label="모델" type="text" value={form.model} onChange={(e) => set("model", e.target.value)} /></label>
      </section>

      <section>
        <h2 className="section-title">알림</h2>
        <label className="field"><span className="flabel">Discord 웹훅</span>
          <input aria-label="Discord 웹훅" type="text" value={form.discord_webhook_url}
            onChange={(e) => set("discord_webhook_url", e.target.value)} /></label>
      </section>
    </div>
  );
}
