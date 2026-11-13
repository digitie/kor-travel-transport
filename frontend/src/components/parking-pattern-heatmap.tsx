"use client";

import dynamic from "next/dynamic";
import { useMemo, useState } from "react";
import { heatCellDescription, parkingHeatCells, type ParkingPatternRow } from "../lib/parking-chart-model";
import type { WeekdayHourBucket } from "../lib/types";

const HeatmapCanvas = dynamic(() => import("./parking-pattern-heatmap-canvas").then((module) => module.ParkingHeatmapCanvas), { ssr: false, loading: () => <p role="status">히트맵을 불러오는 중입니다.</p> });
export function ParkingPatternHeatmap({ rows }: { rows: ParkingPatternRow[] }) {
  const cells = useMemo(() => parkingHeatCells(rows), [rows]);
  const [selection, setSelection] = useState<string | null>(null);
  const selectedCell = cells.find((cell) => `${rows[cell.row].key}/${cell.hour}` === selection);
  return <section className="parking-pattern-chart" aria-label="시간대별 잔여면 히트맵">
    <div className="parking-pattern-scroll"><HeatmapCanvas rows={rows} cells={cells} onSelect={(index) => { const cell = cells[index]; if (cell) setSelection(`${rows[cell.row].key}/${cell.hour}`); }} /></div>
    <p aria-live="polite">{selectedCell ? heatCellDescription(selectedCell) : "셀에 마우스를 올리거나 눌러 평균·최저·최고 잔여면과 관측 수를 확인하세요. 아래 수치 표에서도 키보드로 같은 상세를 열 수 있습니다. 빈 칸은 관측 없음입니다."}</p>
  </section>;
}

export function ParkingPatternCellDetails({ label, bucket }: { label: string; bucket?: WeekdayHourBucket }) {
  if (!bucket || bucket.average_available_spaces === null || !Number.isFinite(bucket.average_available_spaces) || bucket.average_available_spaces < 0 || bucket.observations <= 0) {
    return <><span aria-hidden="true">-</span><span className="sr-only">관측 없음</span></>;
  }
  const description = heatCellDescription({ row: 0, hour: bucket.hour, label, bucket });
  return <details className="parking-pattern-cell-details">
    <summary aria-label={`${description} · 상세 보기`}>{bucket.average_available_spaces}</summary>
    <p>{description}</p>
  </details>;
}
