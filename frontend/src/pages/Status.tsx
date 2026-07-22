import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { getStatus, type StatusResponse } from "../statusApi";
import { SPRING_UI } from "../design/springs";

const POLL_MS = 3000;

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

  const col = s.activity.collector;
  const wrk = s.activity.worker;

  return (
    <main className="page">
      <motion.div
        className="page-head"
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={SPRING_UI}
      >
        <div>
          <h1>상태</h1>
          <p className="sub">서버가 지금 무엇을 실행 중인지 실시간으로 봅니다.</p>
        </div>
      </motion.div>

      <motion.div
        className="summary-strip"
        initial={{ opacity: 0, y: 8 }}
        animate={{ opacity: 1, y: 0 }}
        transition={SPRING_UI}
      >
        <span className="pill">백로그 {s.counts.pending}</span>
        <span className={s.llm_health === "ok" ? "pill pill-good" : "pill pill-bad"}>LLM {s.llm_health}</span>
        <span className={s.enabled ? "pill pill-good" : "pill"}>{s.enabled ? "수집 ON" : "수집 OFF"}</span>
      </motion.div>

      <motion.section
        className="card"
        initial={{ opacity: 0, y: 12 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ ...SPRING_UI, delay: 0.05 }}
      >
        <div className="card-h">파이프라인</div>
        <MonitorRow name="수집기" live={!!col}
          stage={col ? col.stage : "idle"} detail={col?.detail} progress={col?.progress} />
        <MonitorRow name="워커" live={!!wrk}
          stage={wrk ? wrk.stage : "idle"} detail={wrk?.detail} progress={wrk?.progress} />
        {s.activity.research.length === 0 ? (
          <MonitorRow name="리서치" stage="idle" live={false} />
        ) : (
          s.activity.research.map((r) => (
            <MonitorRow key={r.detail_key} name="리서치" live
              stage={r.stage} detail={r.detail || r.detail_key} />
          ))
        )}
      </motion.section>
    </main>
  );
}
