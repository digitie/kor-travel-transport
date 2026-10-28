import { transportGet, TransportError, hasFuelPrice, seoulDate, type FuelPrice } from "./journey";

export type FuelHistoryWindow = { from_at: string; to_at: string; mode: "rolling"; timezone: "Asia/Seoul" };
export type FuelStationHistory = {
  station_id: number; source: string; provider_id: string | null; brand_code: string | null; brand_name: string | null;
  window: FuelHistoryWindow; items: (FuelPrice & { collected_at?: string | null })[]; latest: FuelPrice[];
  meta: { generated_at: string; source_collected_at: string | null; source_status: string | null; item_count: number };
  source_last_success_at: string | null; source_revision: string | null; has_more: boolean; next_cursor: string | null;
};
export type FuelHistoryPoint = FuelPrice & { price: number; instant: number; day: string };
export type FuelHistorySeries = { product: string; points: FuelHistoryPoint[] };
export const FUEL_HISTORY_PRODUCT_ORDER = ["B027", "D047", "B034", "K015", "C004"];

export function fuelHistorySeries(data: Pick<FuelStationHistory, "items" | "window">): FuelHistorySeries[] {
  const start = Date.parse(data.window.from_at), end = Date.parse(data.window.to_at);
  if (!Number.isFinite(start) || !Number.isFinite(end) || start >= end) return [];
  const groups = new Map<string, Map<number, FuelHistoryPoint>>();
  for (const row of data.items) {
    const instant = Date.parse(row.observed_at);
    if (!hasFuelPrice(row) || !row.product_code || !Number.isFinite(instant) || instant < start || instant > end) continue;
    const group = groups.get(row.product_code) ?? new Map<number, FuelHistoryPoint>();
    if (!group.has(instant)) group.set(instant, { ...row, price: row.price!, instant, day: seoulDate(0, instant) });
    groups.set(row.product_code, group);
  }
  const order = (code: string) => { const index = FUEL_HISTORY_PRODUCT_ORDER.indexOf(code); return index < 0 ? FUEL_HISTORY_PRODUCT_ORDER.length : index; };
  return [...groups.entries()].sort(([a], [b]) => order(a) - order(b) || a.localeCompare(b)).map(([product, points]) => ({ product, points: [...points.values()].sort((a, b) => a.instant - b.instant) }));
}

export function isFuelHistoryGap(a: FuelHistoryPoint, b: FuelHistoryPoint) {
  return Date.parse(b.day) - Date.parse(a.day) > 86_400_000;
}

/** 한 번 고정한 창의 모든 페이지를 읽는다. 변경된 revision의 다른 창을 섞지 않는다. */
export async function loadFuelStationHistory(id: number, source: string, signal: AbortSignal): Promise<FuelStationHistory> {
  for (let attempt = 0; attempt < 2; attempt++) {
    try {
      let cursor: string | null = null, first: FuelStationHistory | undefined;
      const items: FuelStationHistory["items"] = [], seen = new Set<string>();
      do {
        signal.throwIfAborted();
        const params = new URLSearchParams({ source, days: "7", limit: "1000" });
        if (cursor) params.set("cursor", cursor);
        const page = await transportGet<FuelStationHistory>(`transport/fuel/stations/${id}/price-history?${params}`, signal);
        if (page.station_id !== id || page.source !== source || first && (page.window.from_at !== first.window.from_at || page.window.to_at !== first.window.to_at || page.source_revision !== first.source_revision)) throw new Error("주유소 가격 이력의 조회 기준이 일치하지 않습니다. 다시 조회해 주세요.");
        first ??= page;
        items.push(...page.items);
        cursor = page.has_more ? page.next_cursor : null;
        if (page.has_more && (!cursor || seen.has(cursor) || seen.size >= 50)) throw new Error("가격 이력 전체를 확인하지 못했습니다. 다시 조회해 주세요.");
        if (cursor) seen.add(cursor);
      } while (cursor);
      return { ...first!, items, has_more: false, next_cursor: null };
    } catch (error) {
      if (!(error instanceof TransportError && error.status === 409 && attempt === 0) || signal.aborted) throw error;
    }
  }
  throw new Error("가격 이력의 조회 기준이 바뀌었습니다. 다시 조회해 주세요.");
}
