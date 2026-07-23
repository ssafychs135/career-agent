import { yearLabel } from "../career";

/** 이중 손잡이 범위 슬라이더 — 하나로 최소·최대를 함께 설정.
 *  두 개의 겹친 range input(썸만 pointer-events 활성)으로 구현.
 *  값 라벨은 각 손잡이 아래를 따라다닌다(기본값이면 양끝=스케일 역할). */

const THUMB = 20;      // 썸 지름(px) — CSS의 thumb 크기와 반드시 일치
const R = THUMB / 2;   // 반지름 보정: 네이티브 range 썸은 트랙 안쪽으로 R만큼 들여져 이동

export default function RangeSlider({
  min, max, lo, hi, onChange,
}: {
  min: number; max: number; lo: number; hi: number;
  onChange: (lo: number, hi: number) => void;
}) {
  const frac = (v: number) => (v - min) / (max - min);
  // 썸 중심 x — pct(%)에 반지름 보정(px)을 더해 실제 이동 범위[R, W-R]에 정렬.
  // 보정 없으면 양 끝에서 fill·라벨이 썸 밖으로 삐져나온다.
  const center = (v: number) => {
    const f = frac(v);
    return `calc(${(f * 100).toFixed(3)}% + ${(R * (1 - 2 * f)).toFixed(2)}px)`;
  };
  const fillRight = () => {
    const f = frac(hi);
    return `calc(${((1 - f) * 100).toFixed(3)}% - ${(R * (1 - 2 * f)).toFixed(2)}px)`;
  };
  // 라벨 중심을 썸에 맞추되 가장자리에서 잘리지 않게 clamp.
  const labelLeft = (v: number) => `clamp(1.1rem, ${center(v)}, calc(100% - 1.1rem))`;

  return (
    <div className="range-wrap">
      <div className="range">
        <div className="range-track" />
        <div className="range-fill" style={{ left: center(lo), right: fillRight() }} />
        <input
          className="range-in" type="range" min={min} max={max} value={lo} aria-label="최소 연차"
          onChange={(e) => onChange(Math.min(Number(e.target.value), hi), hi)}
        />
        <input
          className="range-in" type="range" min={min} max={max} value={hi} aria-label="최대 연차"
          onChange={(e) => onChange(lo, Math.max(Number(e.target.value), lo))}
        />
      </div>
      <div className="range-scale" aria-hidden="true">
        <span className="range-val" style={{ left: labelLeft(lo) }}>{yearLabel(lo, max)}</span>
        <span className="range-val" style={{ left: labelLeft(hi) }}>{yearLabel(hi, max)}</span>
      </div>
    </div>
  );
}
