"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { BarChart, LineChart } from "echarts/charts";
import { GridComponent, MarkLineComponent, MarkPointComponent, TooltipComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { normalizeColor } from "./evilcharts/ui/echarts-chart";
import { CHART_TOKENS as TOKENS, distributionOption, type ChartPalette as Palette, type FuelDistributionChartProps } from "./fuel-distribution-chart-option";

echarts.use([BarChart, LineChart, GridComponent, TooltipComponent, MarkLineComponent, MarkPointComponent]);

/** 시군구 가격 곡선(정렬 분위) + 가격 구간 막대. 공개 유가 화면에서만 지연 적재한다. */
export default function FuelDistributionChart({ distribution, nationwide, productLabel, percent, compare, pinnedPrice, label }: FuelDistributionChartProps) {
  const host = useRef<HTMLDivElement>(null);
  const mount = useRef<HTMLDivElement>(null);
  const [palette, setPalette] = useState<Palette>();
  useEffect(() => {
    const read = () => {
      if (!host.current) return;
      const style = getComputedStyle(host.current);
      const next = Object.fromEntries(TOKENS.map(token => [token, normalizeColor(style.getPropertyValue(token).trim())])) as Palette;
      setPalette(previous => previous && TOKENS.every(token => previous[token] === next[token]) ? previous : next);
    };
    read();
    const observer = new MutationObserver(read);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class", "data-theme", "style"] });
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    media?.addEventListener?.("change", read);
    return () => { observer.disconnect(); media?.removeEventListener?.("change", read); };
  }, []);
  const option = useMemo(() => palette ? distributionOption({ distribution, nationwide, productLabel, percent, compare, pinnedPrice, palette }) : null,
    [distribution, nationwide, productLabel, percent, compare, pinnedPrice, palette]);
  useEffect(() => {
    if (!mount.current || !option) return;
    const chart = echarts.getInstanceByDom(mount.current) ?? echarts.init(mount.current, null, { renderer: "canvas" });
    chart.setOption(option, { notMerge: true });
    const resize = new ResizeObserver(() => chart.resize());
    resize.observe(mount.current);
    return () => resize.disconnect();
  }, [option]);
  useEffect(() => {
    const node = mount.current;
    return () => { if (node) echarts.getInstanceByDom(node)?.dispose(); };
  }, []);
  return <div ref={host} className="fuel-distribution-chart">
    <div ref={mount} className="fuel-distribution-canvas" role="img" aria-label={label} data-testid="fuel-distribution-canvas" />
  </div>;
}
