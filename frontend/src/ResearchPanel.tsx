import { useState } from "react";
import { AnimatePresence, motion } from "motion/react";
import { postJobResearch } from "./researchApi";
import { SPRING_UI, SPRING_MOMENTUM } from "./design/springs";

type Research = {
  status?: string;
  overview?: string;
  stability?: string;
  tech_detail?: string;
  role_detail?: string;
  sources?: string[];
} | null;

type RefetchResult = { companyResearch: Research; jobResearch: Research };

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

/** Pulsing dots — an active, causal "working" signal while research runs (§16 status). */
function Working() {
  return (
    <span style={{ display: "inline-flex", gap: 4, alignItems: "center" }}>
      {[0, 1, 2].map((i) => (
        <motion.span
          key={i}
          animate={{ opacity: [0.25, 1, 0.25] }}
          transition={{ duration: 1, repeat: Infinity, delay: i * 0.16, ease: "easeInOut" }}
          style={{ width: 5, height: 5, borderRadius: 999, background: "var(--accent)" }}
        />
      ))}
    </span>
  );
}

/** A research field — materializes on arrival (rise+fade), not a bare paragraph (§12). */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={SPRING_UI}
      style={{ marginBottom: "var(--sp-4)" }}
    >
      <div className="caption" style={{ marginBottom: 3, fontWeight: 600, color: "var(--text-2)" }}>
        {label}
      </div>
      <div style={{ lineHeight: 1.6, color: "var(--text)" }}>{children}</div>
    </motion.div>
  );
}

export function ResearchPanel({
  source,
  jobId,
  companyResearch,
  jobResearch,
  refetch,
  trigger = postJobResearch,
  pollMs = 2000,
}: {
  source: string;
  jobId: string;
  companyResearch: Research;
  jobResearch: Research;
  refetch: () => Promise<RefetchResult>;
  trigger?: (source: string, jobId: string, force?: boolean) => Promise<unknown>;
  pollMs?: number;
}) {
  const [cr, setCr] = useState<Research>(companyResearch);
  const [jr, setJr] = useState<Research>(jobResearch);
  const [busy, setBusy] = useState(false);

  const done = (r: Research) => r?.status === "done" || r?.status === "failed";

  async function onResearch(force?: boolean) {
    setBusy(true);
    try {
      if (force) {
        await trigger(source, jobId, true);
      } else {
        await trigger(source, jobId);
      }
      for (let i = 0; i < 60; i++) {
        await sleep(pollMs);
        const fresh = await refetch();
        setCr(fresh.companyResearch);
        setJr(fresh.jobResearch);
        if (done(fresh.jobResearch)) break;
      }
    } finally {
      setBusy(false);
    }
  }

  const jrStatus = jr?.status;
  const hasBody = !!(cr?.overview || cr?.stability || jr?.tech_detail || jr?.role_detail);
  const label =
    jrStatus === "done" ? "재리서치" : jrStatus === "failed" ? "재시도" : "리서치 실행";

  return (
    // Parallel, non-blocking surface — translucent, offset, no scrim (§12).
    <motion.section
      className="card"
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...SPRING_UI, delay: 0.08 }}
      style={{ padding: "var(--sp-5)", marginTop: "var(--sp-5)" }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          gap: "var(--sp-3)",
          marginBottom: hasBody || jrStatus ? "var(--sp-4)" : 0,
        }}
      >
        <h2 style={{ fontSize: "1.1rem" }}>🔍 리서치</h2>
        <AnimatePresence mode="wait">
          {(busy || jrStatus === "running") && (
            <motion.span
              key="running"
              className="caption"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              style={{ display: "inline-flex", alignItems: "center", gap: 8 }}
            >
              리서치 중… <Working />
            </motion.span>
          )}
          {!busy && jrStatus === "failed" && (
            <motion.span
              key="failed"
              className="pill pill-bad"
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
            >
              리서치 실패
            </motion.span>
          )}
        </AnimatePresence>
      </div>

      {cr?.overview && <Field label="기업 개요">{cr.overview}</Field>}
      {cr?.stability && <Field label="안정성">{cr.stability}</Field>}
      {jr?.tech_detail && <Field label="기술·문화">{jr.tech_detail}</Field>}
      {jr?.role_detail && <Field label="직무">{jr.role_detail}</Field>}

      {jr?.sources && jr.sources.length > 0 && (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 6, marginBottom: "var(--sp-4)" }}>
          {jr.sources.map((u) => (
            <a
              key={u}
              href={u}
              target="_blank"
              rel="noreferrer"
              className="pill"
              style={{ maxWidth: 260, overflow: "hidden", textOverflow: "ellipsis" }}
            >
              {u.replace(/^https?:\/\//, "")}
            </a>
          ))}
        </div>
      )}

      {jrStatus !== "running" && (
        <motion.button
          className={hasBody ? "" : "btn-primary"}
          onClick={() => onResearch(jrStatus === "done")}
          disabled={busy}
          // Momentum bounce — this fires only from the user's own press (§4).
          whileTap={{ scale: 0.97 }}
          transition={SPRING_MOMENTUM}
        >
          {busy ? "리서치 중…" : label}
        </motion.button>
      )}
    </motion.section>
  );
}
