import { useEffect, useState } from "react";
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

// 폴링 상한 — 백엔드 최악(기업+공고 리서치, 각 파싱 재시도 포함 ~12분)을 덮되
// 프로세스가 중간에 죽어 status가 'running'에 묶인 경우의 무한 폴링은 막는다.
const MAX_POLLS = 450; // × pollMs(2s) ≈ 15분

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

/** 리서치 항목 — 박스 없이 hanging-label(라벨|본문) 문서 행. 도착 시 rise+fade(§12). */
function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <motion.div
      className="field"
      initial={{ opacity: 0, y: 6 }}
      animate={{ opacity: 1, y: 0 }}
      transition={SPRING_UI}
    >
      <div className="flabel">{label}</div>
      <div className="fbody">{children}</div>
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

  async function onResearch(force?: boolean) {
    setBusy(true);
    try {
      if (force) {
        await trigger(source, jobId, true);
      } else {
        await trigger(source, jobId);
      }
      // 202 반환 시점엔 서버가 이미 status='running'으로 마킹한 상태.
      // 한 번 당겨와 아래 폴링 이펙트를 깨운다(이후 갱신은 이펙트가 담당).
      const fresh = await refetch();
      setCr(fresh.companyResearch);
      setJr(fresh.jobResearch);
    } finally {
      setBusy(false);
    }
  }

  // status가 'running'인 동안 폴링. 클릭 핸들러가 아니라 상태에 매달아서,
  // 재마운트·새로고침·다른 경로에서 시작된 리서치도 갱신된다.
  // refetch는 렌더마다 새 함수라 의존성에서 제외(source/jobId가 대신 식별).
  useEffect(() => {
    if (jr?.status !== "running") return;
    let alive = true;
    let ticks = 0;
    const id = setInterval(async () => {
      if (++ticks > MAX_POLLS) {
        clearInterval(id);
        return;
      }
      let fresh: RefetchResult;
      try {
        fresh = await refetch();
      } catch {
        return; // 일시 오류는 다음 틱에 재시도
      }
      if (!alive) return; // 언마운트/공고 전환 후 stale 반영 방지
      setCr(fresh.companyResearch);
      setJr(fresh.jobResearch);
    }, pollMs);
    return () => {
      alive = false;
      clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [jr?.status, source, jobId, pollMs]);

  const jrStatus = jr?.status;
  const hasBody = !!(cr?.overview || cr?.stability || jr?.tech_detail || jr?.role_detail);
  const label =
    jrStatus === "done" ? "재리서치" : jrStatus === "failed" ? "재시도" : "리서치 실행";

  return (
    // 문서 흐름 안의 한 섹션 — 별도 카드 박스 없이 리딩에 녹아든다.
    <motion.section
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ ...SPRING_UI, delay: 0.08 }}
    >
      <h2
        className="section-title"
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: "var(--sp-3)",
        }}
      >
        <span>리서치</span>
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
      </h2>

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
          // 분석 내용과 액션 버튼을 확실히 분리(§16 여백으로 그룹핑)
          style={{ marginTop: "var(--sp-5)" }}
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
