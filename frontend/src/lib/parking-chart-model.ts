import type { WeekdayHourBucket } from "./types";

export type ParkingChartLot = {
  parking_lot_id: number;
  airport_code?: string;
  parking_lot_name: string;
  terminal?: string | null;
  total_spaces: number;
  available_spaces: number;
  occupied_spaces?: number;
  observed_at: string;
};

export function parkingCounts(lot: ParkingChartLot) {
  const { total_spaces: total, available_spaces: available, occupied_spaces: occupied } = lot;
  if (![total, available].every(Number.isSafeInteger) || total <= 0 || available < 0 || available > total) return null;
  if (occupied !== undefined && (!Number.isSafeInteger(occupied) || occupied !== total - available)) return null;
  return { total, available, occupied: total - available };
}

// P1/P2처럼 명시된 시설 번호만 겹친다. 이름이 같다는 이유로 다른 터미널을 합치지 않는다.
export function groupParkingLots(lots: ParkingChartLot[]) {
  const groups = new Map<string, ParkingChartLot[]>();
  for (const lot of lots) {
    const name = lot.parking_lot_name.normalize("NFKC").toUpperCase().replace(/\s+/g, " ").trim();
    const hasNumber = /\bP\s*\d+\b/.test(name) || /P\s*\d+$/.test(name);
    const base = name.replace(/P\s*\d+\b/g, "P");
    const key = hasNumber ? `${lot.airport_code ?? ""}|${lot.terminal ?? ""}|${base}` : `lot:${lot.parking_lot_id}`;
    const group = groups.get(key) ?? [];
    group.push(lot);
    groups.set(key, group);
  }
  return [...groups.values()].flatMap((group) => {
    const chunks: ParkingChartLot[][] = [];
    for (let i = 0; i < group.length; i += 5) chunks.push(group.slice(i, i + 5));
    return chunks;
  });
}

export type ParkingPatternRow = { key: string; label: string; hourly_buckets: WeekdayHourBucket[] };
export type ParkingHeatCell = { row: number; hour: number; label: string; bucket: WeekdayHourBucket };
export function parkingHeatCells(rows: ParkingPatternRow[]): ParkingHeatCell[] {
  return rows.flatMap((row, index) => row.hourly_buckets.filter((bucket) =>
    Number.isInteger(bucket.hour) && bucket.hour >= 0 && bucket.hour < 24 &&
    bucket.observations > 0 && bucket.average_available_spaces !== null &&
    Number.isFinite(bucket.average_available_spaces) && bucket.average_available_spaces >= 0,
  ).map((bucket) => ({ row: index, hour: bucket.hour, label: row.label, bucket })));
}

export function heatCellDescription(cell: ParkingHeatCell) {
  const b = cell.bucket;
  return `${cell.label} ${cell.hour}시 · 평균 ${b.average_available_spaces}면 · 최저 ${b.min_available_spaces ?? "미제공"}면 · 최고 ${b.max_available_spaces ?? "미제공"}면 · 관측 ${b.observations}개`;
}
