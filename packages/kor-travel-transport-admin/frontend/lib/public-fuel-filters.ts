/**
 * 공개 유가(TRANSPORT_UI_MODE=fuel) 주유소 필터. 값은 서버(`/v1/transport/features/places`,
 * `/v1/transport/fuel/price-distribution`)가 적용하므로 마커·묶음·개수·평균·시군구 통계·지도 최저가가 함께 맞는다.
 * 근거 필드는 backend/app/services/fuel_station_filters.py 머리말. 직영·면세유·화물차 우대는 근거가 없어 없다.
 */
export type PublicFuelFilters = {
  /** 빈 배열 = 전체 상표(필터 없음). */
  brands: string[];
  open_24h: boolean;
  self_only: boolean;
  carwash: boolean;
  maintenance: boolean;
  cvs: boolean;
  kpetro: boolean;
  /** 지도 최저가 + N원 이하만. null = 끔. 유종 하나를 고른 때만 쓴다. */
  near_min: number | null;
};

export const DEFAULT_PUBLIC_FUEL_FILTERS: PublicFuelFilters = {
  brands: [], open_24h: false, self_only: false, carwash: false, maintenance: false, cvs: false, kpetro: false, near_min: null,
};

export const FLAG_FILTERS = [
  { key: "open_24h", label: "'24시' 만" },
  { key: "self_only", label: "'셀프주유' 만" },
  { key: "carwash", label: "'자동세차' 만" },
  { key: "maintenance", label: "'경정비' 만" },
  { key: "cvs", label: "'편의점' 만" },
  { key: "kpetro", label: "'품질인증주유소' 만" },
] as const satisfies readonly { key: keyof PublicFuelFilters; label: string }[];

/** 화면 상표 묶음(서버 BRAND_GROUPS와 같은 키). icon은 lib/fuel-brands.ts 코드. lpgOnly는 LPG 충전 전용 상표. */
export const BRAND_FILTERS = [
  { key: "SKE", label: "SK에너지", icon: "SKE" },
  { key: "GSC", label: "GS칼텍스", icon: "GSC" },
  { key: "HDO", label: "HD현대오일뱅크", icon: "HDO" },
  { key: "SOL", label: "S-OIL", icon: "SOL" },
  { key: "ALT", label: "알뜰주유소", icon: "RTO" },
  { key: "NHO", label: "NH-OIL(농협)", icon: "NHO" },
  { key: "RTX", label: "EX-OIL(고속)", icon: "RTX" },
  { key: "NCO", label: "남해화학클린오일", icon: "NCO" },
  { key: "SKG", label: "SK가스", icon: "SKG", lpgOnly: true },
  { key: "E1G", label: "E1", icon: "E1G", lpgOnly: true },
  { key: "ETC", label: "기타", icon: "ETC" },
] as const;
export const ALL_BRAND_KEYS: string[] = BRAND_FILTERS.map(brand => brand.key);
export const NEAR_MIN_STEPS = [10, 20, 30, 50, 70, 100, 150, 200] as const;

/** LPG를 고르지 않은(또는 LPG 밖 유종만 고른) 상태에서는 LPG 충전 전용 상표가 결과에 영향을 주지 않는다. */
export function brandRelevant(brand: (typeof BRAND_FILTERS)[number], products: string[]) {
  return !("lpgOnly" in brand && brand.lpgOnly) || !products.length || products.includes("K015");
}

export function isBrandChecked(filters: PublicFuelFilters, key: string) {
  return !filters.brands.length || filters.brands.includes(key);
}

/** 상표 하나를 켜고 끈다. 모두 켜지면 빈 배열(전체)로, 모두 꺼지는 것은 막는다(빈 결과 대신 마지막 하나를 유지). */
export function toggleBrand(filters: PublicFuelFilters, key: string, checked: boolean): PublicFuelFilters {
  const current = new Set(filters.brands.length ? filters.brands : ALL_BRAND_KEYS);
  if (checked) current.add(key); else current.delete(key);
  if (!current.size) return filters;
  const brands = ALL_BRAND_KEYS.filter(value => current.has(value));
  return { ...filters, brands: brands.length === ALL_BRAND_KEYS.length ? [] : brands };
}

/** 실제로 서버에 보내는 필터 수. 지도 최저가는 유종 하나일 때만 센다(그 밖에는 보내지 않는다). */
export function activeFilterCount(filters: PublicFuelFilters, products?: string[]) {
  const near = filters.near_min != null && (products === undefined || products.length === 1);
  return FLAG_FILTERS.filter(flag => filters[flag.key]).length + (filters.brands.length ? 1 : 0) + (near ? 1 : 0);
}

/** 서버 query. near_min은 유종 하나일 때만 보낸다(서버는 그 밖을 422로 거절한다). */
export function publicFuelFilterQuery(filters: PublicFuelFilters, products: string[]) {
  const search = new URLSearchParams();
  // 고른 유종과 무관한 상표(LPG 전용 상표를 휘발유에서)는 보내지 않는다. 남는 상표가 없으면 상표 조건을 두지 않는다.
  const brands = filters.brands.filter(key => {
    const brand = BRAND_FILTERS.find(item => item.key === key);
    return brand ? brandRelevant(brand, products) : false;
  });
  if (filters.brands.length && brands.length) search.set("brands", brands.join(","));
  for (const flag of FLAG_FILTERS) if (filters[flag.key]) search.set(flag.key, "true");
  if (filters.near_min != null && products.length === 1) search.set("near_min", String(filters.near_min));
  return search.toString();
}

export function parsePublicFuelFilters(value: string | null): PublicFuelFilters {
  if (!value) return DEFAULT_PUBLIC_FUEL_FILTERS;
  try {
    const parsed: unknown = JSON.parse(value);
    if (!parsed || typeof parsed !== "object") return DEFAULT_PUBLIC_FUEL_FILTERS;
    const record = parsed as Record<string, unknown>;
    const brands = Array.isArray(record.brands)
      ? ALL_BRAND_KEYS.filter(key => (record.brands as unknown[]).includes(key)) : [];
    const near = typeof record.near_min === "number" && (NEAR_MIN_STEPS as readonly number[]).includes(record.near_min) ? record.near_min : null;
    return {
      brands: brands.length === ALL_BRAND_KEYS.length ? [] : brands,
      ...Object.fromEntries(FLAG_FILTERS.map(flag => [flag.key, record[flag.key] === true])) as Pick<PublicFuelFilters, (typeof FLAG_FILTERS)[number]["key"]>,
      near_min: near,
    };
  } catch {
    return DEFAULT_PUBLIC_FUEL_FILTERS;
  }
}
