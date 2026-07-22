import { useEffect, useState } from "react";
import { getStatus, type StatusResponse } from "../statusApi";

const POLL_MS = 3000;

function Slot({ name, act }: { name: string; act: { stage: string; detail: string; progress: string } | null }) {
  return (
    <div className="status-row">
      <span className="flabel">{name}</span>
      {act ? (
        <span><span>{act.stage}</span> {act.progress && `· ${act.progress}`} <span className="caption">{act.detail}</span></span>
      ) : (
        <span className="caption">idle</span>
      )}
    </div>
  );
}

export default function Status() {
  const [s, setS] = useState<StatusResponse | null>(null);

  useEffect(() => {
    let alive = true;
    const tick = async () => { try { const r = await getStatus(); if (alive) setS(r); } catch { /* keep last */ } };
    tick();
    const id = setInterval(tick, POLL_MS);
    return () => { alive = false; clearInterval(id); };
  }, []);

  if (!s) return <p className="caption" style={{ margin: "var(--sp-5)" }}>불러오는 중…</p>;

  return (
    <div className="doc" style={{ maxWidth: 640 }}>
      <h1>상태</h1>
      <div style={{ display: "flex", gap: 8, marginBottom: "var(--sp-4)" }}>
        <span className="pill">백로그 {s.counts.pending}</span>
        <span className={s.llm_health === "ok" ? "pill" : "pill pill-bad"}>LLM {s.llm_health}</span>
        <span className="pill">{s.enabled ? "수집 ON" : "수집 OFF"}</span>
      </div>
      <section>
        <Slot name="수집기" act={s.activity.collector} />
        <Slot name="워커" act={s.activity.worker} />
        {s.activity.research.length === 0 ? (
          <div className="status-row"><span className="flabel">리서치</span><span className="caption">idle</span></div>
        ) : (
          s.activity.research.map((r) => (
            <div className="status-row" key={r.detail_key}>
              <span className="flabel">리서치</span>
              <span>{r.stage} <span className="caption">{r.detail || r.detail_key}</span></span>
            </div>
          ))
        )}
      </section>
    </div>
  );
}
