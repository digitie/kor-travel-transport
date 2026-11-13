"use client";

import dynamic from "next/dynamic";
import { VirtualTable, type ColumnDef } from "@kor-travel/ui/virtual-table";
import { useCallback, useMemo, useState } from "react";
import { dailyLineOptions } from "./evilcharts/parking-line-options";

const ParkingLineCanvas = dynamic(() => import("./evilcharts/parking-line-canvas").then((module) => module.ParkingLineCanvas), { ssr: false, loading: () => <p role="status">하루 흐름 차트를 불러오는 중입니다.</p> });

import {
  formatAxisTimeLabel,
  formatDateTime,
  formatNumber,
  formatSeoulDateKey,
  getSeoulDateParts,
} from "../lib/format";
import type { FlightStatusItem, FlightStatusResponse, HolidayItemSummary, ParkingTimeSeriesResponse } from "../lib/types";

const BASE_CHART_WIDTH = 1180;
const CHART_HEIGHT = 320;
const CHART_PADDING_X = 42;
const CHART_PADDING_TOP = 30;
const WEEKDAYS = ["일", "월", "화", "수", "목", "금", "토"];

type DailyFlightOverlayChartProps = {
  flightStatus: FlightStatusResponse | null;
  holidays: HolidayItemSummary[];
  series: ParkingTimeSeriesResponse | null;
  scopeLabel: string;
};

type DailyPoint = {
  bucketAt: string;
  minuteOfDay: number;
  availableSpaces: number | null;
};

type SpecialDayType = "holiday" | "saturday" | "sunday";

type DailyLine = {
  localDate: string;
  label: string;
  specialDayName: string | null;
  specialDayType: SpecialDayType | null;
  points: DailyPoint[];
};

type FlightMarker = FlightStatusItem & {
  key: string;
  x: number;
  y: number;
  label: string;
};

function formatLocalDateLabel(localDate: string): string {
  const [year, month, day] = localDate.split("-").map(Number);
  if (!year || !month || !day) {
    return localDate;
  }
  const weekday = WEEKDAYS[new Date(Date.UTC(year, month - 1, day)).getUTCDay()];
  return `${month}/${day} (${weekday})`;
}

function getWeekendType(localDate: string): SpecialDayType | null {
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

function minuteToX(minuteOfDay: number, chartWidth: number): number {
  const innerWidth = chartWidth - CHART_PADDING_X * 2;
  return CHART_PADDING_X + (Math.min(Math.max(minuteOfDay, 0), 1440) / 1440) * innerWidth;
}

function buildDailyLines(
  series: ParkingTimeSeriesResponse | null,
  holidays: HolidayItemSummary[]
): DailyLine[] {
  if (!series || series.items.length === 0) {
    return [];
  }

  const holidayByDate = new Map(holidays.map((holiday) => [holiday.local_date, holiday.name] as const));
  const grouped = new Map<string, DailyPoint[]>();

  for (const item of series.items) {
    const { hour, minute } = getSeoulDateParts(item.bucket_at);
    const localDate = formatSeoulDateKey(item.bucket_at);
    const points = grouped.get(localDate) ?? [];
    points.push({
      bucketAt: item.bucket_at,
      minuteOfDay: hour * 60 + minute,
      availableSpaces: item.lot_observations > 0 ? item.available_spaces : null,
    });
    grouped.set(localDate, points);
  }

  return Array.from(grouped.entries())
    .filter(([, points]) => points.some((point) => point.availableSpaces !== null))
    .sort(([leftDate], [rightDate]) => leftDate.localeCompare(rightDate))
    .slice(-7)
    .map(([localDate, points]) => {
      const holidayName = holidayByDate.get(localDate) ?? null;
      const weekendType = holidayName ? null : getWeekendType(localDate);
      return {
        localDate,
        label: formatLocalDateLabel(localDate),
        specialDayName: holidayName ?? (weekendType === "saturday" ? "토요일" : weekendType === "sunday" ? "일요일" : null),
        specialDayType: holidayName ? "holiday" : weekendType,
        points: points.sort((left, right) => left.minuteOfDay - right.minuteOfDay),
      };
    });
}

function formatFlightDirection(direction: FlightStatusItem["direction"]): string {
  if (direction === "departure") {
    return "출발";
  }
  if (direction === "arrival") {
    return "도착";
  }
  return "운항";
}

function buildFlightLabel(flight: FlightStatusItem): string {
  const statusLabel = flight.status ? ` (${flight.status})` : "";
  const airlineLabel = flight.airline ? `${flight.airline} ` : "";
  return `${formatDateTime(flight.marker_at)} ${formatFlightDirection(flight.direction)} ${airlineLabel}${flight.flight_number} ${flight.origin_airport} -> ${flight.destination_airport}${statusLabel}`;
}

function buildFlightMarkers(flightStatus: FlightStatusResponse | null, chartWidth: number): FlightMarker[] {
  if (!flightStatus || flightStatus.items.length === 0) {
    return [];
  }

  return flightStatus.items.map((flight, index) => {
    const { hour, minute } = getSeoulDateParts(flight.marker_at);
    return {
      ...flight,
      key: `${flight.direction}-${flight.marker_at}-${flight.origin_airport}-${flight.destination_airport}-${flight.flight_number}`,
      x: minuteToX(hour * 60 + minute, chartWidth),
      y: CHART_PADDING_TOP + 10 + (index % 4) * 9,
      label: buildFlightLabel(flight),
    };
  });
}

export function DailyFlightOverlayChart({
  flightStatus,
  holidays,
  series,
  scopeLabel,
}: DailyFlightOverlayChartProps) {
  const [hiddenDates, setHiddenDates] = useState<Set<string>>(() => new Set());
  const [showDepartures, setShowDepartures] = useState(true);
  const [showArrivals, setShowArrivals] = useState(true);
  const [useWideAxis, setUseWideAxis] = useState(false);
  const [hoveredFlightKey, setHoveredFlightKey] = useState<string | null>(null);
  const [selectedFlightKey, setSelectedFlightKey] = useState<string | null>(null);

  const chartWidth = BASE_CHART_WIDTH * (useWideAxis ? 4 : 1);
  const dailyLines = useMemo(() => buildDailyLines(series, holidays), [holidays, series]);
  const maxValue = Math.max(...dailyLines.flatMap((line) => line.points.map((point) => point.availableSpaces ?? 0)), 1);
  const visibleLines = useMemo(() => dailyLines.filter((line) => !hiddenDates.has(line.localDate)), [dailyLines, hiddenDates]);
  const flightMarkers = useMemo(
    () =>
      buildFlightMarkers(flightStatus, chartWidth).filter((marker) => {
        if (marker.direction === "departure") {
          return showDepartures;
        }
        if (marker.direction === "arrival") {
          return showArrivals;
        }
        return showDepartures || showArrivals;
      }),
    [chartWidth, flightStatus, showArrivals, showDepartures]
  );
  const departureCount = flightMarkers.filter((marker) => marker.direction === "departure").length;
  const arrivalCount = flightMarkers.filter((marker) => marker.direction === "arrival").length;
  const activeFlightKey = hoveredFlightKey ?? selectedFlightKey;
  const activeFlight = activeFlightKey ? flightMarkers.find((marker) => marker.key === activeFlightKey) ?? null : null;
  const selectFlight = useCallback((key: string) => setSelectedFlightKey((current) => current === key ? null : key), []);
  // Hover/selection updates the DOM overlay, not the full series/Graphic lifetime under the pointer.
  const chartOptions = useMemo(() => dailyLineOptions({ lines: visibleLines, allDates: dailyLines.map((line) => line.localDate), width: chartWidth, maxValue,
    flights: flightMarkers, activeFlightKey: null, onHover: setHoveredFlightKey, onSelect: selectFlight }),
    [visibleLines, dailyLines, chartWidth, maxValue, flightMarkers, selectFlight]);

  function toggleDate(localDate: string) {
    setHiddenDates((current) => {
      const next = new Set(current);
      if (next.has(localDate)) {
        next.delete(localDate);
      } else {
        next.add(localDate);
      }
      return next;
    });
  }

  return (
    <article className="panel-surface panel-full-span daily-overlay-panel">
      <div className="panel-head">
        <div>
          <h3>일 단위 잔여 주차면 변화</h3>
          <p>최근 7일 · {scopeLabel}</p>
        </div>
      </div>

      {dailyLines.length === 0 ? (
        <p className="notice">표시할 날짜별 시계열 데이터가 없습니다.</p>
      ) : (
        <>
          <div className="daily-overlay-controls">
            <div className="daily-date-toggle-group" data-testid="daily-date-toggles">
              {dailyLines.map((line) => {
                const isHidden = hiddenDates.has(line.localDate);
                return (
                  <button
                    key={line.localDate}
                    aria-pressed={!isHidden}
                    className={`daily-date-toggle ${line.specialDayType ? `special-day ${line.specialDayType}` : ""} ${
                      isHidden ? "is-off" : ""
                    }`}
                    type="button"
                    onClick={() => toggleDate(line.localDate)}
                  >
                    <strong>{line.label}</strong>
                    {line.specialDayName ? <small>{line.specialDayName}</small> : null}
                  </button>
                );
              })}
            </div>

            <div className="flight-toggle-group" data-testid="flight-direction-toggles">
              <label className="toggle-check">
                <input
                  checked={showDepartures}
                  type="checkbox"
                  onChange={(event) => setShowDepartures(event.target.checked)}
                />
                <span>출발편</span>
              </label>
              <label className="toggle-check">
                <input
                  checked={showArrivals}
                  type="checkbox"
                  onChange={(event) => setShowArrivals(event.target.checked)}
                />
                <span>도착편</span>
              </label>
              <label className="toggle-check">
                <input
                  checked={useWideAxis}
                  data-testid="daily-wide-axis-toggle"
                  type="checkbox"
                  onChange={(event) => setUseWideAxis(event.target.checked)}
                />
                <span>X축 4배</span>
              </label>
            </div>
          </div>

          <div className="daily-overlay-chart-shell" data-testid="daily-flight-overlay-chart">
            <div className="daily-overlay-chart-stage" style={{ width: `${chartWidth}px` }}>
              {activeFlight ? (
                <div
                  className="flight-highlight-label daily-flight-highlight"
                  data-testid="daily-flight-highlight-label"
                  style={{ left: `${activeFlight.x}px` }}
                >
                  <strong>
                    {formatAxisTimeLabel(activeFlight.marker_at)} {activeFlight.flight_number}
                  </strong>
                  <span>{activeFlight.label}</span>
                </div>
              ) : null}

              <ParkingLineCanvas height={CHART_HEIGHT} label={`최근 7일 ${scopeLabel} 일 단위 잔여 주차면 변화`}
                options={chartOptions} />
              {activeFlight ? <div aria-hidden="true" style={{ position: "absolute", pointerEvents: "none", left: activeFlight.x, top: CHART_PADDING_TOP, height: CHART_HEIGHT - CHART_PADDING_TOP - 32, borderLeft: `3px solid var(--color-chart-flight-${activeFlight.direction})` }} /> : null}
            </div>
            <div className="daily-flight-marker-list" aria-label="비행편 선택" role="group">
              {flightMarkers.map((marker) => (
                <button
                  key={`button-${marker.key}`}
                  aria-label={marker.label}
                  aria-pressed={marker.key === selectedFlightKey}
                  className={`daily-flight-marker-button daily-flight-marker-button-${marker.direction} ${
                    marker.key === activeFlightKey ? "active" : ""
                  }`}
                  data-testid="daily-flight-marker-button"
                  type="button"
                  onClick={() => setSelectedFlightKey((current) => (current === marker.key ? null : marker.key))}
                  onFocus={() => setHoveredFlightKey(marker.key)}
                  onBlur={() => setHoveredFlightKey(null)}
                  onMouseEnter={() => setHoveredFlightKey(marker.key)}
                  onMouseLeave={() => setHoveredFlightKey(null)}
                >
                  <strong>
                    {formatAxisTimeLabel(marker.marker_at)} {marker.flight_number}
                  </strong>
                  <small>{formatFlightDirection(marker.direction)}</small>
                </button>
              ))}
            </div>
          </div>

          <DailyValues lines={visibleLines} />
          <div className="daily-overlay-legend">
            {flightStatus?.status === "loading" ? (
              <span role="status">{flightStatus.error_message}</span>
            ) : (
              <>
                <span>비행편 출발 {formatNumber(departureCount)}편 / 도착 {formatNumber(arrivalCount)}편</span>
                {flightStatus?.error_message ? <span className="flight-marker-error">{flightStatus.error_message}</span> : null}
              </>
            )}
          </div>
        </>
      )}
    </article>
  );
}

const dailyValueColumns: ColumnDef<DailyPoint>[] = [
  { id: "time", header: "시각", meta: { rowHeader: true }, cell: ({ row }) => formatAxisTimeLabel(row.original.bucketAt) },
  { id: "available", header: "잔여면", meta: { align: "right" }, cell: ({ row }) => row.original.availableSpaces === null ? "관측 없음" : formatNumber(row.original.availableSpaces) },
];

function DailyValues({ lines }: { lines: DailyLine[] }) {
  const [showValues, setShowValues] = useState(false);
  return (
          <details onToggle={(event) => setShowValues(event.currentTarget.open)}><summary>날짜별 관측 수치 보기</summary>
            {showValues ? lines.map((line) => <VirtualTable key={line.localDate} ariaLabel={`${line.label} ${line.specialDayName ?? ""} 잔여면`}
              caption={`${line.label} ${line.specialDayName ?? ""}`} columns={dailyValueColumns} data={line.points}
              getRowId={(point) => point.bucketAt} virtualized={false} />) : null}
          </details>
  );
}
