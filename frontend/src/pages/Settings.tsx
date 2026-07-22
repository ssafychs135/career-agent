import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { getSettings, putSettings, runCollect, runWorker, type Settings as S } from "../settingsApi";
import ChipInput from "../components/ChipInput";
import Segmented from "../components/Segmented";
import { SPRING_UI, stagger } from "../design/springs";

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

  // 카드 진입 애니메이션 — 순차 stagger(§16 hierarchy)
  const card = (i: number) => ({
    className: "card",
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: stagger(i),
  });

  return (
    <main className="page">
      <motion.div
        className="page-head"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={SPRING_UI}
      >
        <div>
          <h1>설정</h1>
          <p className="sub">수집·워커·알림 손잡이를 한 곳에서 관리합니다.</p>
        </div>
        <button className="btn-primary" onClick={save} disabled={!dirty || busy}>저장</button>
      </motion.div>

      <div className="stack">
        <motion.section {...card(1)}>
          <div className="card-h">수집 제어</div>
          <div className="form-row">
            <span className="rl">수집 활성화</span>
            <input className="switch" type="checkbox" aria-label="수집 활성화"
              checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
          </div>
          <div className="run-bar">
            <button onClick={() => doRun(runCollect, "수집")} disabled={dirty || busy}>지금 수집</button>
            <button onClick={() => doRun(runWorker, "워커")} disabled={dirty || busy}>워커 1회</button>
            <span className="caption">{dirty ? "먼저 저장하세요" : runMsg}</span>
          </div>
        </motion.section>

        <motion.section {...card(2)}>
          <div className="card-h">수집기</div>
          <div className="form-row wide">
            <span className="rl">키워드</span>
            <div className="control"><ChipInput mode="text" value={form.keywords}
              onChange={(v) => set("keywords", v as string[])} /></div>
          </div>
          <div className="form-row wide">
            <span className="rl">원티드 카테고리</span>
            <div className="control"><ChipInput mode="number" value={form.allowed_wanted_categories}
              onChange={(v) => set("allowed_wanted_categories", v as number[])} /></div>
          </div>
          <label className="form-row num">
            <span className="rl">경력 상한(년)</span>
            <input className="control" aria-label="경력 상한" type="number" value={form.max_career_years} onChange={num("max_career_years")} />
          </label>
          <label className="form-row num">
            <span className="rl">페이지 상한</span>
            <input className="control" aria-label="페이지 상한" type="number" value={form.max_pages} onChange={num("max_pages")} />
          </label>
          <label className="form-row num">
            <span className="rl">수집 시각(시)</span>
            <input className="control" aria-label="수집 시각" type="number" value={form.collect_hour} onChange={num("collect_hour")} />
            <span className="hint">저장 시 즉시 재적용</span>
          </label>
        </motion.section>

        <motion.section {...card(3)}>
          <div className="card-h">워커</div>
          <label className="form-row num">
            <span className="rl">배치 크기</span>
            <input className="control" aria-label="배치 크기" type="number" value={form.batch_size} onChange={num("batch_size")} />
          </label>
          <label className="form-row num">
            <span className="rl">재시도(회)</span>
            <input className="control" aria-label="재시도" type="number" value={form.max_attempts} onChange={num("max_attempts")} />
          </label>
          <label className="form-row num">
            <span className="rl">워커 주기(분)</span>
            <input className="control" aria-label="워커 주기" type="number" value={form.worker_interval_min} onChange={num("worker_interval_min")} />
            <span className="hint">저장 시 즉시 재적용</span>
          </label>
          <div className="form-row">
            <span className="rl">요약 백엔드</span>
            <div className="control"><Segmented value={form.summary_backend}
              options={[{ label: "로컬 LLM", value: "local" }, { label: "claude", value: "claude" }]}
              onChange={(v) => set("summary_backend", v)} /></div>
          </div>
          <label className="form-row">
            <span className="rl">모델</span>
            <input className="control" aria-label="모델" type="text" value={form.model} onChange={(e) => set("model", e.target.value)} />
          </label>
        </motion.section>

        <motion.section {...card(4)}>
          <div className="card-h">알림</div>
          <label className="form-row wide">
            <span className="rl">Discord 웹훅</span>
            <input className="control" aria-label="Discord 웹훅" type="text" placeholder="https://discord.com/api/webhooks/…"
              value={form.discord_webhook_url} onChange={(e) => set("discord_webhook_url", e.target.value)} />
          </label>
        </motion.section>
      </div>
    </main>
  );
}
