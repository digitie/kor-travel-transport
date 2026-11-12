"use client";

import { HeatmapChart } from "echarts/charts";
import { GridComponent, VisualMapComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { EChartsHeatmapChart } from "./evilcharts/charts/echarts-heatmap-chart";
import { escapeTooltipHtml } from "./evilcharts/ui/echarts-tooltip";
import { heatCellDescription, type ParkingHeatCell, type ParkingPatternRow } from "../lib/parking-chart-model";

echarts.use([HeatmapChart, GridComponent, VisualMapComponent]);
const config = { available: { label: "잔여 주차면", colors: { light: ["#e8f4ef", "#168766"] } } };
export function ParkingHeatmapCanvas({ rows, cells, onSelect }: { rows: ParkingPatternRow[]; cells: ParkingHeatCell[]; onSelect: (index: number) => void }) {
  return <div style={{ height: Math.max(280, rows.length * 28 + 90) }}><EChartsHeatmapChart className="parking-heatmap-canvas" data={[]} range="2026-01" config={config} animation={false} onDataSelect={onSelect} chartOptions={{
    calendar: [], grid: { top: 8, bottom: 60, left: 115, right: 12 },
    xAxis: { type: "category", data: Array.from({ length: 24 }, (_, hour) => `${hour}시`), splitArea: { show: true }, axisLabel: { interval: 1 } },
    yAxis: { type: "category", inverse: true, data: rows.map((row) => row.label), splitArea: { show: true }, axisLabel: { width: 105, overflow: "truncate" } },
    visualMap: { min: 0, max: Math.max(1, ...cells.map((cell) => cell.bucket.average_available_spaces ?? 0)), calculable: false, orient: "horizontal", left: "center", bottom: 0, inRange: { color: ["#eff6f3", "#168766"] }, text: ["잔여 많음", "적음"] },
    tooltip: { trigger: "item", triggerOn: "mousemove|click", confine: true, formatter: (p: { dataIndex: number }) => cells[p.dataIndex] ? escapeTooltipHtml(heatCellDescription(cells[p.dataIndex])) : "관측 없음" },
    series: [{ id: "parking-matrix", type: "heatmap", data: cells.map((cell) => [cell.hour, cell.row, cell.bucket.average_available_spaces]), label: { show: false }, emphasis: { itemStyle: { borderWidth: 2, borderColor: "#334155" } } }],
  }}><EChartsHeatmapChart.Cell dataKey="available" /></EChartsHeatmapChart></div>;
}
