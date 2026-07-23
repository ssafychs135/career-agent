import { useEffect, useRef, useState } from "react";
import { motion } from "motion/react";
import { getHealth, getClaudeCheck } from "../api";
import { getStatus, type StatusResponse } from "../statusApi";
import {
  getSettings, putSettings, runCollect, runNotify, runWorker, type Settings as S,
} from "../settingsApi";
import ChipInput from "../components/ChipInput";
import Segmented from "../components/Segmented";
import { SPRING_UI, stagger } from "../design/springs";
import { getRuns, type RunLogItem } from "../runsApi";
import { pipelineLabel, triggerLabel, statusClass, runSummary, durationLabel, relativeTime } from "../runsFormat";

const POLL_MS = 3000;

type Probe = { value: string; state: "loading" | "ok" | "error" };
function probeClass(p: Probe): string {
  if (p.state === "ok") return "pill pill-good";
  if (p.state === "error") return "pill pill-bad";
  return "pill";
}

function MonitorRow({
  name, stage, detail, progress, live,
}: { name: string; stage: string; detail?: string; progress?: string; live: boolean }) {
  return (
    <div className={`monitor-row ${live ? "live" : "idle"}`}>
      <span className="mrl"><span className="mdot" />{name}</span>
      <span>
        <span className="stage">{stage}</span>
        {detail && <div className="mdetail">{detail}</div>}
      </span>
      <span className="prog">{progress}</span>
    </div>
  );
}

export default function Ops() {
  // ── 설정(편집 상태) ──
  const [form, setForm] = useState<S | null>(null);
  const [saved, setSaved] = useState<S | null>(null);
  const [busy, setBusy] = useState(false);
  const [runMsg, setRunMsg] = useState("");
  const [notifyMsg, setNotifyMsg] = useState("");
  // ── 상태(폴링) ──
  const [status, setStatus] = useState<StatusResponse | null>(null);
  // ── 헬스 프로브(1회) ──
  const [api, setApi] = useState<Probe>({ value: "…", state: "loading" });
  const [claude, setClaude] = useState<Probe>({ value: "…", state: "loading" });
  const [runs, setRuns] = useState<RunLogItem[]>([]);
  const refreshRuns = () => getRuns(30).then((r) => setRuns(r.items)).catch(() => { /* keep last */ });

  useEffect(() => { getSettings().then((s) => { setForm(s); setSaved(s); }); }, []);

  useEffect(() => { refreshRuns(); }, []);

  useEffect(() => {
    let alive = true;
    const tick = async () => { try { const r = await getStatus(); if (alive) setStatus(r); } catch { /* keep last */ } };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  useEffect(() => {
    getHealth().then((r) => setApi({ value: r.status, state: "ok" })).catch(() => setApi({ value: "error", state: "error" }));
    getClaudeCheck().then(() => setClaude({ value: "ok", state: "ok" })).catch(() => setClaude({ value: "error", state: "error" }));
  }, []);

  const dirty = !!form && !!saved && JSON.stringify(form) !== JSON.stringify(saved);
  const set = <K extends keyof S>(k: K, v: S[K]) => form && setForm({ ...form, [k]: v });
  const num = (k: keyof S) => (e: React.ChangeEvent<HTMLInputElement>) => set(k, Number(e.target.value) as never);

  async function save() {
    if (!form) return;
    setBusy(true);
    try { const r = await putSettings(form); setForm(r); setSaved(r); }
    finally { setBusy(false); }
  }
  async function doRun<T>(fn: () => Promise<T>, format: (r: T) => string, setMsg: (s: string) => void = setRunMsg) {
    setBusy(true); setMsg("실행 중…");
    try { setMsg(format(await fn())); }
    catch { setMsg("실패 · 다시 시도하세요"); }
    finally { setBusy(false); refreshRuns(); }
  }

  const card = (i: number, extra = "") => ({
    className: `card ${extra}`.trim(),
    initial: { opacity: 0, y: 12 },
    animate: { opacity: 1, y: 0 },
    transition: stagger(i),
  });

  const col = status?.activity.collector ?? null;
  const wrk = status?.activity.worker ?? null;
  const active = !!col || !!wrk;
  const prevActive = useRef(false);
  useEffect(() => {
    if (prevActive.current && !active) refreshRuns();
    prevActive.current = active;
  }, [active]);

  return (
    <main className="page">
      <motion.div className="page-head"
        initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={SPRING_UI}>
        <div>
          <h1>운영</h1>
          <p className="sub">서버 상태를 보고, 수집·워커·알림을 한 곳에서 관리합니다.</p>
        </div>
        <button className="btn-primary" onClick={save} disabled={!dirty || busy}>저장</button>
      </motion.div>

      {/* ① 상태 요약 — 헬스 프로브 + /status 요약 통합 */}
      <motion.div className="summary-strip"
        initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }} transition={SPRING_UI}>
        <span className={probeClass(api)}>API {api.value}</span>
        <span className={probeClass(claude)}>Claude {claude.value}</span>
        {status && <span className={status.llm_health === "ok" ? "pill pill-good" : "pill pill-bad"}>LLM {status.llm_health}</span>}
        {status && <span className="pill">백로그 {status.counts.pending}</span>}
        {status && <span className={status.enabled ? "pill pill-good" : "pill"}>{status.enabled ? "수집 ON" : "수집 OFF"}</span>}
      </motion.div>

      <div className="ops-grid">
        {/* ② 파이프라인 — 제어(토글+실행) + 라이브 모니터, 전폭 피처드 */}
        <motion.section {...card(1, "span-2")}>
          <div className="card-h">파이프라인</div>
          {form && (
            <div className="pipe-bar">
              <label className="sw">수집 활성화
                <input className="switch" type="checkbox" aria-label="수집 활성화"
                  checked={form.enabled} onChange={(e) => set("enabled", e.target.checked)} />
              </label>
              <span className="sp" />
              <button onClick={() => doRun(runCollect, (r) => `수집 완료 · 스크레이핑 ${r.scraped} · 적재 ${r.inserted}`)} disabled={dirty || busy}>지금 수집</button>
              <button onClick={() => doRun(runWorker, (r) => r.skipped_tick ? "요약 처리 건너뜀 · LLM 대기 중" : `요약 처리 완료 · ${r.done}건${r.failed ? ` · 실패 ${r.failed}` : ""}`)} disabled={dirty || busy}>요약 처리 1회</button>
              <span className="caption">{dirty ? "먼저 저장하세요" : runMsg}</span>
            </div>
          )}
          <div className="pipe-monitor">
            {!status ? (
              <p className="caption" style={{ margin: 0 }}>불러오는 중…</p>
            ) : (
              <>
                <MonitorRow name="수집기" live={!!col} stage={col ? col.stage : "idle"} detail={col?.detail} progress={col?.progress} />
                <MonitorRow name="워커" live={!!wrk} stage={wrk ? wrk.stage : "idle"} detail={wrk?.detail} progress={wrk?.progress} />
                {status.activity.research.length === 0 ? (
                  <MonitorRow name="리서치" stage="idle" live={false} />
                ) : (
                  status.activity.research.map((r) => (
                    <MonitorRow key={r.detail_key} name="리서치" live stage={r.stage} detail={r.detail || r.detail_key} />
                  ))
                )}
              </>
            )}
          </div>
        </motion.section>

        {/* ③ 설정 — 수집기 · 워커 2단, 알림 풋터 전폭 */}
        {form && (
          <>
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

          <motion.section {...card(4, "span-2")}>
            <div className="card-h">알림</div>
            <label className="form-row wide">
              <span className="rl">Discord 웹훅</span>
              <input className="control" aria-label="Discord 웹훅" type="text" placeholder="https://discord.com/api/webhooks/…"
                value={form.discord_webhook_url} onChange={(e) => set("discord_webhook_url", e.target.value)} />
            </label>
            <div className="form-row">
              <span className="rl">알림 활성화</span>
              <div className="control">
                <input className="switch" type="checkbox" aria-label="알림 활성화"
                  checked={form.notify_enabled} onChange={(e) => set("notify_enabled", e.target.checked)} />
              </div>
            </div>
            <div className="run-bar">
              <button
                onClick={() => doRun(runNotify, (r) => `발송 ${r.sent}건${r.skipped ? ` · 건너뜀 ${r.skipped}` : ""}`, setNotifyMsg)}
                disabled={dirty || busy}
              >지금 알림 발송</button>
              <span className="caption">{dirty ? "먼저 저장하세요" : notifyMsg}</span>
            </div>
          </motion.section>

          <motion.section {...card(5, "span-2")}>
            <div className="card-h">실행 로그</div>
            {runs.length === 0 ? (
              <p className="caption" style={{ margin: 0 }}>아직 기록된 실행이 없습니다.</p>
            ) : (
              <ul className="run-log">
                {runs.map((it) => (
                  <li key={it.id} className="run-row">
                    <span className={`rdot ${statusClass(it.status)}`} />
                    <span className="rpipe">{pipelineLabel(it.pipeline)}</span>
                    <span className="pill rtrig">{triggerLabel(it.trigger)}</span>
                    <span className="rsum">{runSummary(it)}</span>
                    <span className="rdur">{durationLabel(it.duration_ms)}</span>
                    <span className="rtime">{relativeTime(it.finished_at, Date.now())}</span>
                  </li>
                ))}
              </ul>
            )}
          </motion.section>
          </>
        )}
      </div>
    </main>
  );
}
