const SEOUL_TIME_ZONE = "Asia/Seoul";
const seoulPartsFormatter = new Intl.DateTimeFormat("en-CA", {
    year: "numeric",
    month: "numeric",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: SEOUL_TIME_ZONE,
});

const dayLabelFormatter = new Intl.DateTimeFormat("ko-KR", {
    month: "numeric",
    day: "numeric",
    timeZone: SEOUL_TIME_ZONE,
  });
const currencyFormatter = new Intl.NumberFormat("ko-KR", {
    style: "currency",
    currency: "KRW",
    maximumFractionDigits: 0,
  });
const numberFormatter = new Intl.NumberFormat("ko-KR");
const ISO_WITH_TIME_ZONE = /(Z|[+-]\d{2}:\d{2})$/i;

function normalizeApiDate(value: string): string {
  const trimmed = value.trim();
  if (ISO_WITH_TIME_ZONE.test(trimmed)) {
    return trimmed;
  }
  return `${trimmed}Z`;
}

export function parseApiDate(value: string): Date {
  return new Date(normalizeApiDate(value));
}

/**
 * Formats a JS Date's browser-local calendar fields as YYYY-MM-DD. Intentionally reads
 * local (not Asia/Seoul) fields: a date picker's day cells are themselves constructed as
 * browser-local midnight for that grid position, so reading local fields back recovers
 * exactly the calendar day the user clicked, regardless of the browser's own timezone -
 * the API treats the resulting string as an opaque Asia/Seoul calendar-day label, so no
 * timezone conversion belongs here. Use `seoulDateBoundary` instead when you need to turn
 * an API timestamp into a Date comparable against day-picker grid cells (e.g. disabled-day
 * bounds) - that direction DOES need an explicit Asia/Seoul reading.
 */
export function toDateKey(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/**
 * Converts an API timestamp into a browser-local Date at midnight representing the same
 * Asia/Seoul calendar day - safe to compare against date-picker grid cells (which are also
 * browser-local midnight) via day-difference helpers like react-day-picker's `before`/
 * `after` matchers, regardless of the viewer's own timezone.
 */
export function seoulDateBoundary(value: string): Date {
  const { year, month, day } = getSeoulDateParts(value);
  return new Date(year, month - 1, day);
}

export function formatDateTime(value: string): string {
  const { month, day, hour, minute } = getSeoulDateParts(value);
  return `${String(month).padStart(2, "0")}.${String(day).padStart(2, "0")} ${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function formatDateTimeWithZone(value: string): string {
  return `${formatDateTime(value)} KST`;
}

export function getSeoulDateParts(value: string): { year: number; month: number; day: number; hour: number; minute: number } {
  const parts = seoulPartsFormatter.formatToParts(parseApiDate(value));
  const partMap = new Map(parts.map((part) => [part.type, part.value]));

  return {
    year: Number(partMap.get("year") ?? "0"),
    month: Number(partMap.get("month") ?? "0"),
    day: Number(partMap.get("day") ?? "0"),
    hour: Number(partMap.get("hour") ?? "0"),
    minute: Number(partMap.get("minute") ?? "0"),
  };
}

export function formatSeoulDateKey(value: string): string {
  const { year, month, day } = getSeoulDateParts(value);
  return `${String(year).padStart(4, "0")}-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}`;
}

export function formatDayLabel(value: string): string {
  return dayLabelFormatter.format(parseApiDate(value));
}

export function formatAxisDateLabel(value: string): string {
  const { month, day } = getSeoulDateParts(value);
  return `${month}.${day}`;
}

export function formatAxisTimeLabel(value: string): string {
  const { hour, minute } = getSeoulDateParts(value);
  return `${String(hour).padStart(2, "0")}:${String(minute).padStart(2, "0")}`;
}

export function formatMinutesOfDay(value: number | null): string {
  if (value === null) {
    return "-";
  }

  const hours = Math.floor(value / 60);
  const minutes = value % 60;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}`;
}

export function formatCurrency(value: number | null): string {
  if (value === null) {
    return "-";
  }
  return currencyFormatter.format(value);
}

export function formatNumber(value: number): string {
  return numberFormatter.format(value);
}
