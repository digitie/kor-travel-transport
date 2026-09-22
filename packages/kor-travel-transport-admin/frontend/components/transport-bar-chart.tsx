"use client";

import { init, type EChartsOption } from "echarts";
import { useEffect, useRef } from "react";

type ChartItem = { label: string; value: number | null };

export function TransportBarChart({ ariaLabel, items, unit }: { ariaLabel: string; items: ChartItem[]; unit: string }) {
  const node = useRef<HTMLDivElement | null>(null);

  useEffect(() => {
    if (!node.current) return;
    const chart = init(node.current, undefined, { renderer: "canvas" });
    const style = getComputedStyle(document.documentElement);
    const muted = style.getPropertyValue("--muted").trim();
    const accent = style.getPropertyValue("--accent").trim();
    const line = style.getPropertyValue("--line").trim();
    const option: EChartsOption = {
      animationDuration: 220,
      grid: { top: 16, right: 12, bottom: 50, left: 46 },
      tooltip: { trigger: "axis", valueFormatter: (value) => value === null ? "값 없음" : `${Number(value).toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unit}` },
      xAxis: { type: "category", data: items.map((item) => item.label), axisLabel: { color: muted, interval: 0, rotate: items.length > 4 ? 24 : 0 }, axisLine: { lineStyle: { color: line } } },
      yAxis: { type: "value", axisLabel: { color: muted, formatter: (value: number) => `${value}${unit}` }, splitLine: { lineStyle: { color: line } } },
      series: [{ type: "bar", data: items.map((item) => item.value), itemStyle: { color: accent, borderRadius: [5, 5, 0, 0] }, emphasis: { focus: "series" } }],
    };
    chart.setOption(option);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(node.current);
    return () => { observer.disconnect(); chart.dispose(); };
  }, [items, unit]);

  return <>
    <div aria-label={ariaLabel} className="transport-chart" role="img" ref={node} />
    <ul className="sr-only" aria-label={`${ariaLabel} 수치`}>{items.map((item) => <li key={item.label}>{item.label}: {item.value === null ? "값 없음" : `${item.value.toLocaleString("ko-KR", { maximumFractionDigits: 1 })}${unit}`}</li>)}</ul>
  </>;
}
