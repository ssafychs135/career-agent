import { useState } from "react";

type Val = string | number;

export default function ChipInput({
  value, onChange, mode,
}: { value: Val[]; onChange: (v: Val[]) => void; mode: "text" | "number" }) {
  const [draft, setDraft] = useState("");

  function commit() {
    const t = draft.trim();
    if (!t) return;
    let v: Val = t;
    if (mode === "number") {
      if (!/^\d+$/.test(t)) { setDraft(""); return; }  // 비숫자 거부
      v = Number(t);
    }
    if (!value.some((x) => x === v)) onChange([...value, v]);  // 중복 방지
    setDraft("");
  }

  return (
    <div className="chip-input">
      {value.map((v) => (
        <span key={String(v)} className="pill chip">
          {v}
          <button type="button" aria-label={`${v} 제거`} onClick={() => onChange(value.filter((x) => x !== v))}>×</button>
        </span>
      ))}
      <input
        type="text"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); commit(); } }}
        placeholder="입력 후 Enter"
      />
    </div>
  );
}
