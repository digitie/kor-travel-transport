"use client";

import { useMemo } from "react";
import { EChartsPieChart } from "./evilcharts/charts/echarts-pie-chart";
import { escapeTooltipHtml } from "./evilcharts/ui/echarts-tooltip";
import { parkingCounts, type ParkingChartLot } from "../lib/parking-chart-model";

const config = { available: { label: "잔여", colors: { light: ["#168766"], dark: ["#44bd97"] } }, occupied: { label: "사용", colors: { light: ["#cbd5e1"], dark: ["#64748b"] } } };
export function ParkingPie({ lots }: { lots: ParkingChartLot[] }) {
  const series = useMemo(() => lots.flatMap((lot, index) => {
    const counts = parkingCounts(lot);
    if (!counts) return [];
    const step = 70 / lots.length;
    const outer = 88 - index * step;
    return [{ type: "pie", id: `lot-${lot.parking_lot_id}`, name: lot.parking_lot_name,
      radius: [`${Math.max(10, outer - step + 3)}%`, `${outer}%`],
      label: { show: false }, emphasis: { scale: false },
      data: [{ name: "잔여", value: counts.available, itemStyle: { color: "#168766" } }, { name: "사용", value: counts.occupied, itemStyle: { color: "#cbd5e1" } }],
    }];
  }), [lots]);
  if (!series.length) return <p>유효한 주차면 관측이 없습니다.</p>;
  return <EChartsPieChart className="parking-pie-canvas" data={series[0].data.map((item) => ({ name: item.name === "잔여" ? "available" : "occupied", value: item.value }))} config={config} dataKey="value" nameKey="name" animation={false} chartOptions={{ series, tooltip: { trigger: "item", triggerOn: "mousemove|click", confine: true, formatter: (p: { seriesName?: string; name?: string; value?: number; seriesId?: string }) => {
    const lot = lots.find((item) => `lot-${item.parking_lot_id}` === p.seriesId);
    const counts = lot && parkingCounts(lot);
    return `${escapeTooltipHtml(p.seriesName ?? "")}<br/>${escapeTooltipHtml(p.name ?? "")}: ${p.value ?? "미제공"}면${counts ? `<br/>잔여 ${counts.available} / 사용 ${counts.occupied} / 전체 ${counts.total}면` : ""}`;
  } } }}><EChartsPieChart.Pie /></EChartsPieChart>;
}
