"use client";

import type { TimeSeriesPoint } from "../../lib/types";

type Band = { x: number; width: number; name: string; day_type: "holiday" | "saturday" | "sunday" };
type HistoryPoint = TimeSeriesPoint & { x: number; y: number };
type DailyLine = { localDate: string; label: string; specialDayType: string | null; specialDayName: string | null; points: { minuteOfDay: number; availableSpaces: number | null }[] };
type Flight = { key: string; x: number; y: number; label: string; direction: string };
const gridColor = "var(--grid-line)";

/** 기존 SVG의 H→V와 같은 step:end. 결측은 null, 관측된 0은 그대로 전달한다. */
export function historyLineOptions({ points, width, bands, activeIndex }: { points: HistoryPoint[]; width: number; bands: Band[]; activeIndex: number }) {
  const latest = [...points].reverse().find((point) => point.lot_observations > 0);
  const active = points[activeIndex];
  const values = points.map((point) => point.lot_observations > 0 ? point.available_spaces : null);
  return {
    animation: false, grid: { left: 18, right: 18, top: 20, bottom: 20 },
    tooltip: { show: false },
    xAxis: { type: "value", min: 18, max: width - 18, show: false },
    yAxis: { type: "value", min: 0, max: Math.max(1, ...values.map((value) => value ?? 0)), splitNumber: 3, axisLabel: { show: false }, splitLine: { lineStyle: { color: gridColor } } },
    series: [{ id: "parking-history", name: "잔여 주차면", type: "line", step: "end", connectNulls: false,
      data: points.map((point, index) => [point.x, values[index]]),
      showSymbol: true, showAllSymbol: true, symbol: "circle",
      symbolSize: (_value: unknown, params: { dataIndex: number }) => values[params.dataIndex] !== null && (params.dataIndex === 0 || values[params.dataIndex - 1] === null) && (params.dataIndex === values.length - 1 || values[params.dataIndex + 1] === null) ? 8 : 0,
      lineStyle: { color: "var(--teal)", width: 3 }, itemStyle: { color: "var(--teal)" },
      areaStyle: { color: "var(--teal)", opacity: 0.12 },
      markArea: { silent: true, label: { show: true, color: "var(--muted-foreground)", fontSize: 11 }, data: bands.map((band) => [{ name: band.name, xAxis: band.x, itemStyle: { color: `var(--color-chart-${band.day_type}-fill)` } }, { xAxis: band.x + band.width }]) },
      markLine: { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: "var(--color-accent)", type: "dashed" }, data: active ? [{ xAxis: active.x }] : [] },
      markPoint: { silent: true, symbol: "circle", symbolSize: 10, label: { show: false }, data: [latest, active?.lot_observations > 0 ? active : undefined].filter((point): point is HistoryPoint => Boolean(point)).map((point) => ({ coord: [point.x, point.available_spaces], itemStyle: { color: "var(--surface-strong)", borderColor: "var(--teal)", borderWidth: 3 } })) },
    }],
  };
}

export function dailyLineOptions({ lines, allDates, maxValue, flights, activeFlightKey, onHover, onSelect }: {
  lines: DailyLine[]; allDates: string[]; width: number; maxValue: number; flights: Flight[]; activeFlightKey: string | null;
  onHover: (key: string | null) => void; onSelect: (key: string) => void;
}) {
  return {
    animation: false, grid: { left: 42, right: 42, top: 30, bottom: 32 }, tooltip: { show: false },
    xAxis: { type: "value", min: 0, max: 1440, interval: 360, axisLabel: { color: "var(--muted-foreground)", formatter: (minute: number) => `${String(minute / 60).padStart(2, "0")}:00` }, splitLine: { lineStyle: { color: gridColor } } },
    yAxis: { type: "value", min: 0, max: maxValue, splitNumber: 3, axisLabel: { show: false }, splitLine: { lineStyle: { color: gridColor } } },
    series: lines.map((line) => {
      const color = `var(--color-chart-series-${allDates.indexOf(line.localDate) % 7})`;
      const last = [...line.points].reverse().find((point) => point.availableSpaces !== null);
      return { id: line.localDate, name: line.label, type: "line", step: "end", connectNulls: false,
        data: line.points.map((point) => [point.minuteOfDay, point.availableSpaces]),
        showSymbol: true, symbol: "circle", symbolSize: 4,
        lineStyle: { color, width: line.specialDayType ? 3.2 : 2.6, type: line.specialDayType ? "dashed" : "solid" }, itemStyle: { color },
        markPoint: { silent: true, symbol: "rect", symbolSize: 9, label: { show: false }, data: line.specialDayType && last ? [{ name: line.specialDayName, coord: [last.minuteOfDay, last.availableSpaces], itemStyle: { color: "var(--surface-strong)", borderColor: `var(--color-chart-${line.specialDayType})`, borderWidth: 2 } }] : [] },
      };
    }),
    graphic: flights.map((flight) => ({ id: `flight-${flight.key}`, type: "group", cursor: "pointer", z: 10,
      onclick: () => onSelect(flight.key), onmouseover: () => onHover(flight.key), onmouseout: () => onHover(null),
      children: [
        { type: "line", z: 10, shape: { x1: flight.x, x2: flight.x, y1: 30, y2: 288 }, style: { stroke: `var(--color-chart-flight-${flight.direction})`, lineWidth: flight.key === activeFlightKey ? 3 : 1.4, lineDash: flight.key === activeFlightKey ? [] : [4, 5] } },
        { type: "circle", z: 11, shape: { cx: flight.x, cy: flight.y, r: flight.key === activeFlightKey ? 6 : 4.5 }, style: { fill: "var(--surface-strong)", stroke: `var(--color-chart-flight-${flight.direction})`, lineWidth: 2 } },
      ],
    })),
  };
}
