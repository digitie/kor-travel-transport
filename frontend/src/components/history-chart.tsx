"use client";

import dynamic from "next/dynamic";
import { VirtualTable, type ColumnDef } from "@kor-travel/ui/virtual-table";
import { useEffect, useMemo, useRef, useState } from "react";
import { historyLineOptions } from "./evilcharts/parking-line-options";

const ParkingLineCanvas = dynamic(() => import("./evilcharts/parking-line-canvas").then((module) => module.ParkingLineCanvas), { ssr: false, loading: () => <p role="status">주차 이력 차트를 불러오는 중입니다.</p> });

import {
  formatAxisDateLabel,
  formatAxisTimeLabel,
  formatDateTime,
  formatNumber,
  formatSeoulDateKey,
  getSeoulDateParts,
} from "../lib/format";
import type { HolidayItemSummary, ParkingTimeSeriesResponse, TimeSeriesPoint } from "../lib/types";

const CHART_MIN_WIDTH = 1280;
const CHART_HEIGHT = 280;
const CHART_PADDING_X = 18;
const CHART_PADDING_Y = 20;
const TOOLTIP_EDGE_PADDING = 88;
const TOUCH_DRAG_THRESHOLD_PX = 12;

type HistoryChartProps = {
  holidays: HolidayItemSummary[];
  series: ParkingTimeSeriesResponse | null;
  scopeLabel: string;
};

type ChartPoint = TimeSeriesPoint & {
  x: number;
  y: number;
};

type AxisMarker = {
  bucket_at: string;
  x: number;
  dateLabel: string | null;
  timeLabel: string;
};

type SpecialDayType = "holiday" | "saturday" | "sunday";

type SpecialDaySummary = HolidayItemSummary & {
  day_type: SpecialDayType;
};

type HolidayChartBand = SpecialDaySummary & {
  x: number;
  width: number;
  labelX: number;
};

function clamp(value: number, min: number, max: number): number {
  return Math.min(Math.max(value, min), max);
}

function historyRangeLabel(series: ParkingTimeSeriesResponse): string {
  return series.start_date && series.end_date ? `${series.start_date} ~ ${series.end_date}` : `최근 ${series.days}일`;
}

function buildLabelIndexes(points: TimeSeriesPoint[]): number[] {
  if (points.length === 0) {
    return [];
  }

  const indexes = points.reduce<number[]>((collected, point, index) => {
    const { hour, minute } = getSeoulDateParts(point.bucket_at);
    if (minute === 0 && hour % 6 === 0) {
      collected.push(index);
    }
    return collected;
  }, []);

  if (indexes.length === 0) {
    return [0];
  }

  return indexes;
}

function buildChartPoints(points: TimeSeriesPoint[], chartWidth: number): ChartPoint[] {
  const innerWidth = chartWidth - CHART_PADDING_X * 2;
  const innerHeight = CHART_HEIGHT - CHART_PADDING_Y * 2;
  const observedValues = points
    .filter((point) => point.lot_observations > 0)
    .map((point) => point.available_spaces);
  const maxValue = Math.max(...observedValues, 1);

  return points.map((point, index) => ({
    ...point,
    x: CHART_PADDING_X + (index * innerWidth) / Math.max(points.length - 1, 1),
    y: CHART_PADDING_Y + (1 - point.available_spaces / maxValue) * innerHeight,
  }));
}

function buildAxisMarkers(points: ChartPoint[], labelIndexes: number[]): AxisMarker[] {
  return labelIndexes.map((pointIndex, index) => {
    const point = points[pointIndex];
    const { hour } = getSeoulDateParts(point.bucket_at);
    return {
      bucket_at: point.bucket_at,
      x: point.x,
      dateLabel: hour === 0 || index === 0 ? formatAxisDateLabel(point.bucket_at) : null,
      timeLabel: formatAxisTimeLabel(point.bucket_at),
    };
  });
}

function getLocalDateWeekendType(localDate: string): SpecialDayType | null {
  const [year, month, day] = localDate.split("-").map(Number);
  if (!year || !month || !day) {
    return null;
  }
  const weekday = new Date(Date.UTC(year, month - 1, day)).getUTCDay();
  if (weekday === 6) {
    return "saturday";
  }
  if (weekday === 0) {
    return "sunday";
  }
  return null;
}

function buildSpecialDays(holidays: HolidayItemSummary[], points: ChartPoint[]): SpecialDaySummary[] {
  const holidaysByDate = new Map(
    holidays.map((holiday) => [
      holiday.local_date,
      {
        ...holiday,
        day_type: "holiday" as const,
      },
    ])
  );
  const localDates = Array.from(new Set(points.map((point) => formatSeoulDateKey(point.bucket_at)))).sort();

  return localDates.flatMap((localDate) => {
    const holiday = holidaysByDate.get(localDate);
    if (holiday) {
      return [holiday];
    }

    const weekendType = getLocalDateWeekendType(localDate);
    if (!weekendType) {
      return [];
    }

    return [
      {
        local_date: localDate,
        name: weekendType === "saturday" ? "토요일" : "일요일",
        day_type: weekendType,
        weekday: weekendType === "saturday" ? 5 : 6,
        weekday_name: weekendType === "saturday" ? "토" : "일",
      },
    ];
  });
}

function buildSpecialDayBands(
  specialDays: SpecialDaySummary[],
  points: ChartPoint[],
  chartWidth: number
): HolidayChartBand[] {
  if (specialDays.length === 0 || points.length === 0) {
    return [];
  }

  const pointsByDate = new Map<string, ChartPoint[]>();
  for (const point of points) {
    const localDate = formatSeoulDateKey(point.bucket_at);
    pointsByDate.set(localDate, [...(pointsByDate.get(localDate) ?? []), point]);
  }

  const stepWidth =
    points.length > 1 ? (chartWidth - CHART_PADDING_X * 2) / Math.max(points.length - 1, 1) : chartWidth - CHART_PADDING_X * 2;

  return specialDays.flatMap((specialDay) => {
    const matchedPoints = pointsByDate.get(specialDay.local_date) ?? [];
    if (matchedPoints.length === 0) {
      return [];
    }
    const firstPoint = matchedPoints[0];
    const lastPoint = matchedPoints[matchedPoints.length - 1];
    const x = clamp(firstPoint.x - stepWidth / 2, CHART_PADDING_X, chartWidth - CHART_PADDING_X);
    const maxX = clamp(lastPoint.x + stepWidth / 2, CHART_PADDING_X, chartWidth - CHART_PADDING_X);
    return [
      {
        ...specialDay,
        x,
        width: Math.max(maxX - x, 1),
        labelX: x + Math.max(maxX - x, 1) / 2,
      },
    ];
  });
}

export function HistoryChart({ holidays, series, scopeLabel }: HistoryChartProps) {
  const [activeSelection, setActiveSelection] = useState<{ series: HistoryChartProps["series"]; index: number | null }>({ series, index: null });
  const activePointIndex = activeSelection.series === series ? activeSelection.index : null;
  const setActivePointIndex = (index: number | null) => setActiveSelection({ series, index });
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Pointer/keyboard selection only moves the DOM cursor; it does not reparse all ECharts series.
  const plotOptions = useMemo(() => {
    if (!series?.items.length) return null;
    const width = Math.max(CHART_MIN_WIDTH, buildLabelIndexes(series.items).length * 64);
    const points = buildChartPoints(series.items, width);
    const bands = buildSpecialDayBands(buildSpecialDays(holidays, points), points, width);
    return historyLineOptions({ points, width, bands, activeIndex: -1 });
  }, [series, holidays]);

  useEffect(() => {
    if (!series || series.items.length === 0) {
      return;
    }

    const scrollElement = scrollRef.current;
    if (!scrollElement) {
      return;
    }

    scrollElement.scrollLeft = scrollElement.scrollWidth;
  }, [series]);

  if (!series || series.items.length === 0) {
    return (
      <article className="panel-surface history-panel">
        <div className="panel-head">
          <div>
            <h3>{series ? `${historyRangeLabel(series)} 잔여 주차면` : "잔여 주차면"}</h3>
            <p className="history-scope">기준: {scopeLabel}</p>
          </div>
        </div>
        <p className="notice">표시할 과거 시계열 데이터가 없습니다.</p>
      </article>
    );
  }

  const points = series.items;
  const observedPoints = points.filter((point) => point.lot_observations > 0);
  if (observedPoints.length === 0) {
    return (
      <article className="panel-surface history-panel">
        <div className="panel-head">
          <div>
            <h3>{historyRangeLabel(series)} 잔여 주차면</h3>
            <p className="history-scope">기준: {scopeLabel}</p>
          </div>
        </div>
        <p className="notice">표시할 주차 관측 데이터가 없습니다.</p>
      </article>
    );
  }

  const labelIndexes = buildLabelIndexes(points);
  const chartWidth = Math.max(CHART_MIN_WIDTH, labelIndexes.length * 64);
  const chartPoints = buildChartPoints(points, chartWidth);
  const axisMarkers = buildAxisMarkers(chartPoints, labelIndexes);
  const holidayBands = buildSpecialDayBands(buildSpecialDays(holidays, chartPoints), chartPoints, chartWidth);
  const latestPoint = observedPoints[observedPoints.length - 1];
  const defaultActivePointIndex = Math.max(
    chartPoints.findIndex((point) => point.bucket_at === latestPoint.bucket_at),
    0
  );
  const resolvedActivePointIndex =
    activePointIndex !== null && activePointIndex < chartPoints.length ? activePointIndex : defaultActivePointIndex;
  const activePoint = chartPoints[resolvedActivePointIndex];
  const tooltipLeft = clamp(activePoint.x, TOOLTIP_EDGE_PADDING, chartWidth - TOOLTIP_EDGE_PADDING);
  const tooltipTop = clamp(activePoint.y - 12, 60, CHART_HEIGHT - 8);

  function selectObservation(index: number) {
    setActivePointIndex(index);
    const scroll = scrollRef.current;
    if (scroll) scroll.scrollLeft = Math.max(0, chartPoints[index].x - scroll.clientWidth / 2);
  }

  function updateActivePoint(clientX: number, width: number) {
    const svgX = clamp((clientX / width) * chartWidth, CHART_PADDING_X, chartWidth - CHART_PADDING_X);
    const pointIndex = Math.round(
      ((svgX - CHART_PADDING_X) / Math.max(chartWidth - CHART_PADDING_X * 2, 1)) * Math.max(points.length - 1, 0)
    );
    setActivePointIndex(clamp(pointIndex, 0, Math.max(points.length - 1, 0)));
  }


  return (
    <article className="panel-surface history-panel">
      <div className="panel-head">
        <div>
          <h3>{historyRangeLabel(series)} 잔여 주차면</h3>
          <p className="history-scope">기준: {scopeLabel}</p>
        </div>
        <p className="section-hint">마지막 관측 {formatDateTime(latestPoint.bucket_at)}</p>
      </div>

      <div className="history-chart-shell" data-testid="history-chart">
        <div className="history-chart-scroll" ref={scrollRef}>
          <div className="history-chart-stage" style={{ width: `${chartWidth}px` }}>
              <div
                className="history-tooltip"
                data-testid="history-tooltip"
                style={{ left: `${tooltipLeft}px`, top: `${tooltipTop}px` }}
              >
                <strong>
                  {activePoint.lot_observations > 0 ? `${formatNumber(activePoint.available_spaces)}대` : "주차 정보 없음"}
                </strong>
                <span>{formatDateTime(activePoint.bucket_at)}</span>
              </div>

            <ParkingLineCanvas height={CHART_HEIGHT} label={`${historyRangeLabel(series)} ${series.interval_minutes}분 간격 ${scopeLabel} 시계열`}
              options={plotOptions!} />

            <div aria-hidden="true" style={{ position: "absolute", pointerEvents: "none", left: activePoint.x, top: CHART_PADDING_Y, height: CHART_HEIGHT - CHART_PADDING_Y * 2, borderLeft: "1px dashed var(--color-accent)" }} />
            {activePoint.lot_observations > 0 ? <div aria-hidden="true" style={{ position: "absolute", pointerEvents: "none", left: activePoint.x - 6, top: activePoint.y - 6, width: 12, height: 12, borderRadius: "50%", background: "var(--surface-strong)", border: "3px solid var(--teal)" }} /> : null}
            <HistorySurface onSelect={updateActivePoint} onClear={() => setActivePointIndex(null)} />

            <div className="history-axis-shell" data-testid="history-axis-shell">
              {axisMarkers.map((marker) => (
                <span
                  key={`axis-${marker.bucket_at}`}
                  className="history-axis-label"
                  data-testid="history-axis-label"
                  style={{ left: `${marker.x}px` }}
                >
                  {marker.dateLabel ? <strong>{marker.dateLabel}</strong> : <strong className="history-axis-date-spacer" />}
                  <small>{marker.timeLabel}</small>
                </span>
              ))}
            </div>
          </div>
        </div>
      </div>
      <HistoryValues points={points} bands={holidayBands} index={resolvedActivePointIndex} onSelect={selectObservation} />
    </article>
  );
}

const historyValueColumns: ColumnDef<TimeSeriesPoint>[] = [
  { id: "time", header: "시각", meta: { rowHeader: true, wrap: true }, cell: ({ row }) => formatDateTime(row.original.bucket_at) },
  { id: "available", header: "잔여면", meta: { align: "right" }, cell: ({ row }) => row.original.lot_observations > 0 ? formatNumber(row.original.available_spaces) : "관측 없음" },
  { id: "observations", header: "관측 수", meta: { align: "right" }, cell: ({ row }) => row.original.lot_observations },
];

function HistoryValues({ points, bands, index, onSelect }: { points: TimeSeriesPoint[]; bands: HolidayChartBand[]; index: number; onSelect: (index: number) => void }) {
  const [showValues, setShowValues] = useState(false);
  const activePoint = points[index];
  return <>
      <label>관측 시점 선택
        <input type="range" min={0} max={points.length - 1} value={index}
          aria-label="주차 관측 시점" aria-valuetext={`${formatDateTime(activePoint.bucket_at)} · ${activePoint.lot_observations > 0 ? `${formatNumber(activePoint.available_spaces)}대` : "주차 정보 없음"}`}
          onChange={(event) => onSelect(Number(event.target.value))} />
      </label>
      <details onToggle={(event) => setShowValues(event.currentTarget.open)}><summary>관측 수치와 특별일 보기</summary>
        <p>{bands.map((band) => `${band.local_date} ${band.name}`).join(" · ") || "표시 구간에 공휴일·주말 없음"}</p>
        {showValues ? <VirtualTable ariaLabel="실제 주차 관측 수치" caption="실제 주차 관측 수치" columns={historyValueColumns}
          data={points} getRowId={(point) => point.bucket_at} virtualized={false} /> : null}
      </details>
  </>;
}

function HistorySurface({ onSelect, onClear }: { onSelect: (x: number, width: number) => void; onClear: () => void }) {
  const touchGestureRef = useRef<{ startX: number; isHorizontalDrag: boolean } | null>(null);
  function getTouchClientX(touches: { length: number; [index: number]: { clientX: number } }): number | null {
    if (touches.length === 0) {
      return null;
    }
    return touches[0].clientX;
  }

  function updateActivePointFromTouch(target: HTMLDivElement, clientX: number) {
    const bounds = target.getBoundingClientRect();
    onSelect(clientX - bounds.left, bounds.width);
  }

  return (
            <div
              className="history-chart-surface"
              data-testid="history-chart-surface"
              onMouseLeave={() => {
                onClear();
              }}
              onMouseMove={(event) => {
                const bounds = event.currentTarget.getBoundingClientRect();
                onSelect(event.clientX - bounds.left, bounds.width);
              }}
              onTouchMove={(event) => {
                const clientX = getTouchClientX(event.touches);
                if (clientX === null) {
                  return;
                }
                const gesture = touchGestureRef.current;
                if (!gesture) {
                  return;
                }
                if (Math.abs(clientX - gesture.startX) > TOUCH_DRAG_THRESHOLD_PX) {
                  touchGestureRef.current = { ...gesture, isHorizontalDrag: true };
                  return;
                }
                if (!gesture.isHorizontalDrag) {
                  updateActivePointFromTouch(event.currentTarget, clientX);
                }
              }}
              onTouchStart={(event) => {
                const clientX = getTouchClientX(event.touches);
                if (clientX === null) {
                  return;
                }
                touchGestureRef.current = { startX: clientX, isHorizontalDrag: false };
                updateActivePointFromTouch(event.currentTarget, clientX);
              }}
              onTouchEnd={() => {
                touchGestureRef.current = null;
              }}
              onTouchCancel={() => {
                touchGestureRef.current = null;
              }}
            />

  );
}
