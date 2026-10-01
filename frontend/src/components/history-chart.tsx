"use client";

import { useEffect, useRef, useState } from "react";

import {
  formatAxisDateLabel,
  formatAxisTimeLabel,
  formatDateTime,
  formatNumber,
  formatSeoulDateKey,
  getSeoulDateParts,
} from "@/lib/format";
import type { HolidayItemSummary, ParkingTimeSeriesResponse, TimeSeriesPoint } from "@/lib/types";

const CHART_MIN_WIDTH = 1280;
const CHART_HEIGHT = 280;
const CHART_PADDING_X = 18;
const CHART_PADDING_Y = 20;
const GRID_LINES = 4;
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

function buildStepLinePath(points: ChartPoint[]): string {
  if (points.length === 0) {
    return "";
  }

  const path = [`M ${points[0].x} ${points[0].y}`];

  for (let index = 1; index < points.length; index += 1) {
    const point = points[index];
    path.push(`H ${point.x}`);
    path.push(`V ${point.y}`);
  }

  return path.join(" ");
}

function buildStepAreaPath(points: ChartPoint[]): string {
  if (points.length === 0) {
    return "";
  }

  const bottom = CHART_HEIGHT - CHART_PADDING_Y;
  const path = [`M ${points[0].x} ${bottom}`, `L ${points[0].x} ${points[0].y}`];

  for (const point of points.slice(1)) {
    path.push(`H ${point.x}`);
    path.push(`V ${point.y}`);
  }

  path.push(`L ${points[points.length - 1].x} ${bottom}`);
  path.push("Z");
  return path.join(" ");
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
  const [activePointIndex, setActivePointIndex] = useState<number | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const touchGestureRef = useRef<{ startX: number; isHorizontalDrag: boolean } | null>(null);

  useEffect(() => {
    setActivePointIndex(null);

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
  const observedRuns: ChartPoint[][] = [];
  let inObservedRun = false;
  for (const point of chartPoints) {
    if (point.lot_observations > 0) {
      if (!inObservedRun) {
        observedRuns.push([]);
      }
      observedRuns[observedRuns.length - 1].push(point);
      inObservedRun = true;
    } else {
      inObservedRun = false;
    }
  }
  const axisMarkers = buildAxisMarkers(chartPoints, labelIndexes);
  const holidayBands = buildSpecialDayBands(buildSpecialDays(holidays, chartPoints), chartPoints, chartWidth);
  const latestPoint = observedPoints[observedPoints.length - 1];
  const chartPointByBucket = new Map(chartPoints.map((point) => [point.bucket_at, point] as const));
  const latestChartPoint = chartPointByBucket.get(latestPoint.bucket_at);
  const defaultActivePointIndex = Math.max(
    chartPoints.findIndex((point) => point.bucket_at === latestPoint.bucket_at),
    0
  );
  const resolvedActivePointIndex =
    activePointIndex !== null && activePointIndex < chartPoints.length ? activePointIndex : defaultActivePointIndex;
  const activePoint = chartPoints[resolvedActivePointIndex] ?? null;
  const tooltipLeft = activePoint ? clamp(activePoint.x, TOOLTIP_EDGE_PADDING, chartWidth - TOOLTIP_EDGE_PADDING) : 0;
  const tooltipTop = activePoint ? clamp(activePoint.y - 12, 60, CHART_HEIGHT - 8) : 0;

  function updateActivePoint(clientX: number, width: number) {
    const svgX = clamp((clientX / width) * chartWidth, CHART_PADDING_X, chartWidth - CHART_PADDING_X);
    const pointIndex = Math.round(
      ((svgX - CHART_PADDING_X) / Math.max(chartWidth - CHART_PADDING_X * 2, 1)) * Math.max(points.length - 1, 0)
    );
    setActivePointIndex(clamp(pointIndex, 0, Math.max(points.length - 1, 0)));
  }

  function getTouchClientX(touches: { length: number; [index: number]: { clientX: number } }): number | null {
    if (touches.length === 0) {
      return null;
    }
    return touches[0].clientX;
  }

  function updateActivePointFromTouch(target: HTMLDivElement, clientX: number) {
    const bounds = target.getBoundingClientRect();
    updateActivePoint(clientX - bounds.left, bounds.width);
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
            {activePoint ? (
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
            ) : null}

            <svg
              aria-label={`${historyRangeLabel(series)} ${series.interval_minutes}분 간격 ${scopeLabel} 시계열`}
              className="history-chart"
              role="img"
              viewBox={`0 0 ${chartWidth} ${CHART_HEIGHT}`}
            >
              <defs>
                <linearGradient id="history-area-gradient" x1="0" x2="0" y1="0" y2="1">
                  <stop offset="0%" stopColor="rgba(12, 139, 125, 0.24)" />
                  <stop offset="100%" stopColor="rgba(12, 139, 125, 0.02)" />
                </linearGradient>
              </defs>

              {Array.from({ length: GRID_LINES }, (_, index) => {
                const y =
                  CHART_PADDING_Y + ((CHART_HEIGHT - CHART_PADDING_Y * 2) * index) / Math.max(GRID_LINES - 1, 1);
                return (
                  <line
                    key={`grid-${index}`}
                    className="history-grid-line"
                    x1={CHART_PADDING_X}
                    x2={chartWidth - CHART_PADDING_X}
                    y1={y}
                    y2={y}
                  />
                );
              })}

              {axisMarkers.map((marker) => (
                <line
                  key={`divider-${marker.bucket_at}`}
                  className="history-divider"
                  x1={marker.x}
                  x2={marker.x}
                  y1={CHART_PADDING_Y}
                  y2={CHART_HEIGHT - CHART_PADDING_Y}
                />
              ))}

              {holidayBands.map((band) => (
                <g key={`holiday-band-${band.local_date}-${band.day_type}-${band.name}`}>
                  <rect
                    className={`holiday-band holiday-band-${band.day_type}`}
                    data-testid="holiday-band"
                    height={CHART_HEIGHT - CHART_PADDING_Y * 2}
                    width={band.width}
                    x={band.x}
                    y={CHART_PADDING_Y}
                  />
                  <text className="holiday-band-label" textAnchor="middle" x={band.labelX} y={CHART_PADDING_Y - 6}>
                    {band.name}
                  </text>
                </g>
              ))}

              {observedRuns.map((run, index) => (
                <path key={`area-${index}`} className="history-area" d={buildStepAreaPath(run)} />
              ))}
              {observedRuns.map((run, index) => (
                <path key={`line-${index}`} className="history-line" d={buildStepLinePath(run)} fill="none" />
              ))}

              {activePoint ? (
                <>
                  <line
                    className="history-active-line"
                    x1={activePoint.x}
                    x2={activePoint.x}
                    y1={CHART_PADDING_Y}
                    y2={CHART_HEIGHT - CHART_PADDING_Y}
                  />
                  {activePoint.lot_observations > 0 ? (
                    <circle className="history-point active" cx={activePoint.x} cy={activePoint.y} r="6" />
                  ) : null}
                </>
              ) : null}
              {latestChartPoint ? (
                <circle className="history-point latest" cx={latestChartPoint.x} cy={latestChartPoint.y} r="5" />
              ) : null}
            </svg>

            <div
              className="history-chart-surface"
              data-testid="history-chart-surface"
              onMouseLeave={() => {
                setActivePointIndex(null);
              }}
              onMouseMove={(event) => {
                const bounds = event.currentTarget.getBoundingClientRect();
                updateActivePoint(event.clientX - bounds.left, bounds.width);
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
    </article>
  );
}
