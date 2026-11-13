"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { CustomChart, type CustomSeriesOption } from "echarts/charts";
import * as echarts from "echarts/core";
import { EChartsLineChart } from "./evilcharts/charts/echarts-line-chart";
import Link from "next/link";
import { Button } from "./ui/button";
import { normalizeColor } from "./evilcharts/ui/echarts-chart";
import { escapeTooltipHtml as escapeHtml } from "./evilcharts/ui/echarts-tooltip";
import { fuelProductLabel } from "@/lib/transport-presentation";
import { FUEL_CHART_ORDER, fuelChartTime, fuelInstant, fuelLineValues, fuelStationHref, type FuelChartPoint, type FuelChartSeries } from "@/lib/fuel-chart-model";

echarts.use([CustomChart]);
const tokens = ["--brand", "--success", "--warning", "--danger", "--text-secondary"];
const amount = (value?: number | null) => value == null ? "미제공" : value.toLocaleString("ko-KR", { maximumFractionDigits: 2 });
const price = (value?: number | null) => value == null ? "미제공" : `${amount(value)}원/L`;
type TooltipParam = { seriesId?: string; value?: unknown };

export default function FuelPriceChart({ series, label, window, showExtremes = true }: { showExtremes?: boolean; series: FuelChartSeries[]; label: string; window?: { from_at: string; to_at: string } }) {
  const host = useRef<HTMLDivElement>(null);
  const [palette, setPalette] = useState<string[]>([]);
  const [active, setActive] = useState<number | null>(null);
  useEffect(() => {
    const read = () => {
      if (!host.current) return;
      const style = getComputedStyle(host.current);
      const next = [...tokens, "--card", "--text-primary", "--control-line"].map(token => normalizeColor(style.getPropertyValue(token).trim()));
      setPalette(previous => previous.join("|") === next.join("|") ? previous : next);
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme", "style"] });
    if (document.body) observer.observe(document.body, { attributes: true, attributeFilter: ["class", "data-theme", "style"] });
    return () => observer.disconnect();
  }, []);
  const times = useMemo(() => [...new Set(series.flatMap(row => row.points.map(point => fuelInstant(point.time)).filter(Number.isFinite)))].sort((a, b) => a - b), [series]);
  const chartData = useMemo(() => times.map(time => ({ time, value: 0 })), [times]);
  const options = useMemo(() => {
    const colorFor = (product: string, index: number) => palette[(FUEL_CHART_ORDER.indexOf(product) < 0 ? index : FUEL_CHART_ORDER.indexOf(product)) % tokens.length];
    const lookup = new Map<string, Map<number, FuelChartPoint>>();
    const charts = series.flatMap((row, index) => {
      const color = colorFor(row.product, index);
      lookup.set(`${row.product}:average`, new Map(row.points.map(point => [fuelInstant(point.time), point])));
      const renderItem: NonNullable<CustomSeriesOption["renderItem"]> = (_params, api) => {
        const low = api.coord([api.value(0), api.value(1)]), high = api.coord([api.value(0), api.value(2)]);
        const offset = (index - (series.length - 1) / 2) * 4;
        const line = (x1: number, y1: number, x2: number, y2: number) => ({ type: "line" as const, shape: { x1, y1, x2, y2 }, style: { stroke: color, lineWidth: 1.4 } });
        return { type: "group", children: [line(low[0] + offset, low[1], high[0] + offset, high[1]), line(low[0] + offset - 3, low[1], low[0] + offset + 3, low[1]), line(high[0] + offset - 3, high[1], high[0] + offset + 3, high[1])] };
      };
      return [
        { id: `${row.product}:average`, name: fuelProductLabel(row.product), type: "line", data: fuelLineValues(row.points), connectNulls: false, showSymbol: true, symbolSize: 5, lineStyle: { color, width: 2 }, itemStyle: { color }, animation: false },
        { id: `${row.product}:range`, name: `${fuelProductLabel(row.product)} 최저·최고`, type: "custom", renderItem, silent: true, tooltip: { show: false }, data: row.points.filter(point => point.minimum != null && point.maximum != null && point.minimum <= point.maximum && Number.isFinite(fuelInstant(point.time))).map(point => [fuelInstant(point.time), point.minimum, point.maximum]), encode: { x: 0, y: [1, 2] }, animation: false },
      ];
    });
    const formatter = (parameters: TooltipParam | TooltipParam[]) => {
      const rows = (Array.isArray(parameters) ? parameters : [parameters]).flatMap(parameter => {
        if (!Array.isArray(parameter.value) || parameter.value[1] == null) return [];
        const point = lookup.get(parameter.seriesId ?? "")?.get(Number(parameter.value[0]));
        const product = series.find(row => `${row.product}:average` === parameter.seriesId)?.product;
        return point && product ? [{ point, product }] : [];
      });
      const first = rows[0]?.point;
      const commonTime = first && rows.every(({ point }) => point.time === first.time) ? first.time : null;
      const commonGeneration = first?.generated_at && rows.every(({ point }) => point.generated_at === first.generated_at) ? first.generated_at : null;
      const header = `<header>${commonTime ? `<strong>${escapeHtml(fuelChartTime(commonTime))} KST</strong> · ` : ""}원/L${commonGeneration ? `<br/>수집 ${escapeHtml(fuelChartTime(commonGeneration))} KST` : ""}</header>`;
      const values = rows.map(({ point, product }) => {
        const href = fuelStationHref(point.cheapest);
        return `<div class="fuel-chart-tooltip-row"><strong>${escapeHtml(fuelProductLabel(product))}</strong> · ${showExtremes ? "평균" : "가격"} ${escapeHtml(amount(point.average))}${commonTime ? "" : `<br/>${escapeHtml(fuelChartTime(point.time))} KST`}${showExtremes ? `<br/>최저 ${escapeHtml(amount(point.minimum))} · 최고 ${escapeHtml(amount(point.maximum))}` : ""}${point.generated_at && !commonGeneration ? `<br/>수집 ${escapeHtml(fuelChartTime(point.generated_at))} KST` : ""}${point.cheapest ? `<br/>${href ? `<a class="inline-link" href="${escapeHtml(href)}">${escapeHtml(point.cheapest.name)} · 지도</a>` : escapeHtml(point.cheapest.name)}` : ""}</div>`;
      });
      return `<div class="fuel-chart-tooltip">${header}${values.join("")}</div>`;
    };
    return {
      animation: false,
      xAxis: { type: "time", splitNumber: 5, minInterval: 86400000, min: window ? fuelInstant(window.from_at) : undefined, max: window ? fuelInstant(window.to_at) : undefined, axisLabel: { color: palette[4], hideOverlap: true, formatter: (value: number) => fuelChartTime(value).slice(5, 10) } },
      yAxis: { type: "value", scale: true, name: "원/L", axisLabel: { color: palette[4] }, nameTextStyle: { color: palette[4] } },
      grid: { left: 52, right: 18, top: 28, bottom: 28 },
      tooltip: { backgroundColor: palette[tokens.length], borderColor: palette[tokens.length + 2], textStyle: { color: palette[tokens.length + 1] }, show: true, trigger: "axis", triggerOn: "mousemove|click", enterable: true, confine: true, formatter },
      series: charts,
    };
  }, [series, palette, window, showExtremes]);
  const selected = active === null ? null : times[Math.min(active, times.length - 1)];
  return <div ref={host} className="fuel-echarts-block">
    <div className="fuel-echarts" role="group" aria-label={label}>
      {palette.length ? <EChartsLineChart data={chartData} config={{}} xDataKey="time" animation={false} className="h-full" chartOptions={options} /> : <p role="status">차트 준비 중…</p>}
    </div>
    <Button type="button" variant="outline" size="sm" className="sr-only fuel-chart-keyboard" aria-label={`${label} 날짜 선택`} onClick={() => setActive(Math.max(0, times.length - 1))} onKeyDown={event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End", "Escape"].includes(event.key)) return;
      event.preventDefault();
      if (event.key === "Escape") setActive(null);
      else if (event.key === "Home") setActive(0);
      else if (event.key === "End") setActive(Math.max(0, times.length - 1));
      else setActive(value => Math.max(0, Math.min(times.length - 1, (value ?? times.length - 1) + (event.key === "ArrowLeft" ? -1 : 1))));
    }}>날짜별 가격 확인 · 좌우 방향키 / Home / End</Button>
    <p className="sr-only">터치 또는 마우스로 날짜와 최저·최고·평균을 확인합니다. 좌우 방향키로 날짜를 선택할 수 있습니다.</p>
    <div className="fuel-chart-legend">{series.map((row, index) => <span key={row.product} style={{ borderLeft: `3px solid var(${tokens[(FUEL_CHART_ORDER.indexOf(row.product) < 0 ? index : FUEL_CHART_ORDER.indexOf(row.product)) % tokens.length]})`, paddingInlineStart: ".35rem" }}>{fuelProductLabel(row.product)}</span>)}</div>
    {selected !== null ? <div role="status">{series.flatMap(row => row.points.filter(point => fuelInstant(point.time) === selected).map(point => <p key={row.product}>{fuelProductLabel(row.product)} · {fuelChartTime(point.time)} · {showExtremes ? "평균" : "가격"} {price(point.average)}{showExtremes ? <> · 최저 {price(point.minimum)} · 최고 {price(point.maximum)}</> : null} {fuelStationHref(point.cheapest) ? <Link className="inline-link" href={fuelStationHref(point.cheapest)!}>{point.cheapest!.name} · 지도</Link> : point.cheapest?.name}</p>))}</div> : null}
  </div>;
}
