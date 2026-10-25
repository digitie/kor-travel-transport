import type { CSSProperties } from "react";

import { formatNumber } from "./format";
import type { ParkingStatus, ThresholdWeekdayTime, TimeSeriesPoint, WeekdayHourBucket, WeekdayHourlyPattern } from "./types";

export function statusTone(statusLevel: ParkingStatus["status_level"]): string {
  switch (statusLevel) {
    case "full":
      return "tone-full";
    case "critical":
      return "tone-critical";
    case "warning":
      return "tone-warning";
    case "busy":
      return "tone-busy";
    default:
      return "tone-stable";
  }
}

export function statusLabel(statusLevel: ParkingStatus["status_level"]): string {
  switch (statusLevel) {
    case "full":
      return "만차";
    case "critical":
      return "10대 미만";
    case "warning":
      return "50대 미만";
    case "busy":
      return "여유 적음";
    default:
      return "원활";
  }
}

export function formatHourLabel(hour: number): string {
  return `${String(hour).padStart(2, "0")}:00`;
}

export function formatThresholdLabel(threshold: number): string {
  return `${formatNumber(threshold)}대 미만`;
}

export function formatDateCell(localDate: string, weekdayName: string): string {
  const [year, month, day] = localDate.split("-");
  if (!year || !month || !day) {
    return `${localDate} (${weekdayName})`;
  }
  return `${month}.${day} (${weekdayName})`;
}

export function formatHolidayDate(localDate: string, weekdayName: string): string {
  const [year, month, day] = localDate.split("-");
  if (!year || !month || !day) {
    return `${localDate} (${weekdayName})`;
  }
  return `${Number(month)}/${Number(day)} (${weekdayName})`;
}

export function buildAvailabilityHeatStyle(value: number | null, maxValue: number): CSSProperties | undefined {
  if (value === null || maxValue <= 0) {
    return undefined;
  }

  const ratio = Math.min(Math.max(value / maxValue, 0), 1);
  const hue = 6 + ratio * 214;
  const lightness = 88 - ratio * 24;

  return {
    background: `hsl(${hue} 78% ${lightness}%)`,
    borderColor: `hsla(${hue} 72% 38% / 0.16)`,
    color: "#000000",
  };
}

export function summarizeAverageAvailability(patterns: WeekdayHourlyPattern[]): {
  tightest: { weekdayName: string; hour: number; value: number } | null;
  roomiest: { weekdayName: string; hour: number; value: number } | null;
} {
  const observedHours = patterns.flatMap((pattern) =>
    pattern.hourly_buckets
      .filter(
        (bucket): bucket is WeekdayHourBucket & { average_available_spaces: number } =>
          bucket.average_available_spaces !== null && bucket.observations > 0
      )
      .map((bucket) => ({
        weekdayName: pattern.weekday_name,
        hour: bucket.hour,
        value: bucket.average_available_spaces,
      }))
  );

  if (observedHours.length === 0) {
    return { tightest: null, roomiest: null };
  }

  const sorted = [...observedHours].sort((left, right) => left.value - right.value);
  return {
    tightest: sorted[0],
    roomiest: sorted[sorted.length - 1],
  };
}

export function getThresholdWeekdayItem(
  items: ThresholdWeekdayTime[],
  threshold: number,
  weekday: number
): ThresholdWeekdayTime | null {
  return items.find((item) => item.threshold === threshold && item.weekday === weekday) ?? null;
}

export function hasThresholdSamples(items: ThresholdWeekdayTime[]): boolean {
  return items.some((item) => item.sample_count > 0);
}

export function historyLabel(selectedParkingLotName: string | null, airportName: string | undefined): string {
  return selectedParkingLotName ?? `${airportName ?? "공항"} 전체`;
}

export function summarizeTimeSeriesAvailability(items: TimeSeriesPoint[]): {
  min: number | null;
  max: number | null;
  average: number | null;
} {
  const observed = items.filter((item) => item.lot_observations > 0);
  if (observed.length === 0) {
    return { min: null, max: null, average: null };
  }
  const values = observed.map((item) => item.available_spaces);
  const sum = values.reduce((total, value) => total + value, 0);
  return {
    min: Math.min(...values),
    max: Math.max(...values),
    average: Math.round(sum / values.length),
  };
}

export const HOURS = Array.from({ length: 24 }, (_, hour) => hour);
export const WEEKDAYS = ["월", "화", "수", "목", "금", "토", "일"];
export const THRESHOLDS = [50, 10] as const;
