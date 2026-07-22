/** 연차(경력) 표시 유틸. min/max_career(년, null 허용)을 사람이 읽는 문구로. */

/** 슬라이더 눈금 한 값 → 라벨. 0=신입, 상한=이상. */
export function yearLabel(v: number, cap: number): string {
  if (v <= 0) return "신입";
  if (v >= cap) return `${cap}년+`;
  return `${v}년`;
}

/** 공고의 모집 연차 범위 → 문구. (min,max 둘 다 null이면 호출부에서 숨김) */
export function careerLabel(min: number | null, max: number | null): string {
  const lo = min ?? 0;
  if (max == null) return lo === 0 ? "경력 무관" : `${lo}년 이상`;
  if (lo === 0 && max === 0) return "신입";
  if (lo === 0) return `신입~${max}년`;
  if (lo === max) return `${lo}년`;
  return `${lo}~${max}년`;
}
