export interface Facet {
  name: string;
  count: number;
}

export interface Facets {
  regions: Facet[];
  companies: Facet[];
}

/** 필터 UI용 목록 — 전역 필터가 적용되지 않아 숨긴 기업도 포함된다. */
export async function getFacets(): Promise<Facets> {
  const r = await fetch("/api/facets");
  if (!r.ok) throw new Error("facets load failed");
  return r.json();
}
