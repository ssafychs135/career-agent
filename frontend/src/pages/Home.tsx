import { useEffect, useState } from "react";
import { motion } from "motion/react";
import { getHealth, getClaudeCheck } from "../api";
import { SPRING_UI, stagger } from "../design/springs";

type Probe = { value: string; state: "loading" | "ok" | "error" };

/** Status pill class by probe state — status/completion/error feedback (§16). */
function pillClass(p: Probe): string {
  if (p.state === "ok") return "pill pill-good";
  if (p.state === "error") return "pill pill-bad";
  return "pill";
}

export default function Home() {
  const [health, setHealth] = useState<Probe>({ value: "…", state: "loading" });
  const [claude, setClaude] = useState<Probe>({ value: "…", state: "loading" });

  useEffect(() => {
    getHealth()
      .then((r) => setHealth({ value: r.status, state: "ok" }))
      .catch(() => setHealth({ value: "error", state: "error" }));
    getClaudeCheck()
      .then((r) => setClaude({ value: r.reply, state: "ok" }))
      .catch(() => setClaude({ value: "error", state: "error" }));
  }, []);

  const cards: { label: string; sub: string; probe: Probe; testid: string }[] = [
    { label: "API", sub: "백엔드 상태", probe: health, testid: "health" },
    { label: "Claude", sub: "리서치 엔진", probe: claude, testid: "claude" },
  ];

  return (
    <main
      style={{
        maxWidth: 720,
        margin: "0 auto",
        padding: "clamp(2rem, 6vw, 4rem) clamp(1rem, 4vw, 2rem)",
      }}
    >
      <motion.header
        initial={{ opacity: 0, y: 10 }}
        animate={{ opacity: 1, y: 0 }}
        transition={SPRING_UI}
        style={{ marginBottom: "var(--sp-6)" }}
      >
        <h1>career-agent</h1>
        <p style={{ color: "var(--text-2)", margin: "0.4rem 0 0", fontSize: "1.05rem" }}>
          수집된 채용 공고를 열람하고, 기업·공고를 에이전트로 리서치합니다.
        </p>
      </motion.header>

      <div
        style={{
          display: "grid",
          gap: "var(--sp-4)",
          gridTemplateColumns: "repeat(auto-fit, minmax(220px, 1fr))",
        }}
      >
        {cards.map((c, i) => (
          <motion.section
            key={c.testid}
            className="card"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={stagger(i + 1)}
            style={{ padding: "var(--sp-5)" }}
          >
            <div
              style={{
                display: "flex",
                alignItems: "center",
                justifyContent: "space-between",
                marginBottom: "0.6rem",
              }}
            >
              <h3>{c.label}</h3>
              <span className={pillClass(c.probe)}>
                <span data-testid={c.testid}>{c.probe.value}</span>
              </span>
            </div>
            <p className="caption" style={{ margin: 0 }}>
              {c.sub}
            </p>
          </motion.section>
        ))}
      </div>
    </main>
  );
}
