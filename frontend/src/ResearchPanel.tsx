import { useState } from "react";
import { postJobResearch } from "./researchApi";

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

  return (
    <section>
      <h2>🔍 리서치</h2>
      {cr?.overview && (
        <p>
          <strong>기업 개요:</strong> {cr.overview}
        </p>
      )}
      {cr?.stability && (
        <p>
          <strong>안정성:</strong> {cr.stability}
        </p>
      )}
      {jr?.tech_detail && (
        <p>
          <strong>기술·문화:</strong> {jr.tech_detail}
        </p>
      )}
      {jr?.role_detail && (
        <p>
          <strong>직무:</strong> {jr.role_detail}
        </p>
      )}
      {jr?.sources && jr.sources.length > 0 && (
        <ul>
          {jr.sources.map((u) => (
            <li key={u}>
              <a href={u}>{u}</a>
            </li>
          ))}
        </ul>
      )}
      {jrStatus === "running" && <p>리서치 중…</p>}
      {jrStatus === "failed" && <p>리서치 실패</p>}
      {jrStatus !== "running" && (
        <button
          onClick={() => onResearch(jrStatus === "done")}
          disabled={busy}
        >
          {busy
            ? "리서치 중…"
            : jrStatus === "done"
              ? "재리서치"
              : jrStatus === "failed"
                ? "재시도"
                : "리서치 실행"}
        </button>
      )}
    </section>
  );
}
