/** 이중 손잡이 범위 슬라이더 — 하나로 최소·최대를 함께 설정.
 *  두 개의 겹친 range input(썸만 pointer-events 활성)으로 구현. */
export default function RangeSlider({
  min, max, lo, hi, onChange,
}: {
  min: number; max: number; lo: number; hi: number;
  onChange: (lo: number, hi: number) => void;
}) {
  const pct = (v: number) => ((v - min) / (max - min)) * 100;
  return (
    <div className="range">
      <div className="range-track" />
      <div className="range-fill" style={{ left: `${pct(lo)}%`, right: `${100 - pct(hi)}%` }} />
      <input
        className="range-in" type="range" min={min} max={max} value={lo} aria-label="최소 연차"
        onChange={(e) => onChange(Math.min(Number(e.target.value), hi), hi)}
      />
      <input
        className="range-in" type="range" min={min} max={max} value={hi} aria-label="최대 연차"
        onChange={(e) => onChange(lo, Math.max(Number(e.target.value), lo))}
      />
    </div>
  );
}
