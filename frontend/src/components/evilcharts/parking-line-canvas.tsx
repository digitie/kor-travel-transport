"use client";

import { memo, useCallback, useMemo, useState, useSyncExternalStore } from "react";
import { GraphicComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent } from "echarts/components";
import * as echarts from "echarts/core";
import { EChartsLineChart } from "./charts/echarts-line-chart";
import styles from "./parking-line.module.css";

echarts.use([GraphicComponent, MarkAreaComponent, MarkLineComponent, MarkPointComponent]);
const config = { available: { label: "잔여 주차면", colors: { light: ["var(--teal)"] } } };
const tokens = ["--grid-line", "--teal", "--muted-foreground", "--color-accent", "--surface-strong",
  ...["holiday", "saturday", "sunday"].flatMap((day) => [`--color-chart-${day}`, `--color-chart-${day}-fill`]),
  ...Array.from({ length: 7 }, (_, index) => `--color-chart-series-${index}`),
  "--color-chart-flight-departure", "--color-chart-flight-arrival"];
function subscribeTheme(notify: () => void, container: HTMLElement | null) {
  const observer = new MutationObserver(notify);
  for (let element = container ?? document.documentElement; element; element = element.parentElement!) {
    observer.observe(element, { attributes: true, attributeFilter: ["class", "style", "data-theme"] });
  }
  const media = matchMedia("(prefers-color-scheme: dark)");
  media.addEventListener("change", notify);
  return () => { observer.disconnect(); media.removeEventListener("change", notify); };
}
function paletteSnapshot(container: HTMLElement | null) {
  const style = getComputedStyle(container ?? document.documentElement);
  return JSON.stringify(Object.fromEntries(tokens.map((token) => [token, style.getPropertyValue(token).trim()])));
}
function subscribeSize(notify: () => void, container: HTMLElement | null) {
  if (!container) return () => {};
  const observer = new ResizeObserver(notify);
  observer.observe(container);
  return () => observer.disconnect();
}
/** Engine escape-hatch options also resolve the existing light/dark CSS tokens. */
function resolveTokens(value: unknown, palette: Record<string, string>): unknown {
  if (typeof value === "string" && value.startsWith("var(--")) return palette[value.slice(4, -1)] || "#64748b";
  if (Array.isArray(value)) return value.map((item) => resolveTokens(item, palette));
  if (value && typeof value === "object") return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, resolveTokens(item, palette)]));
  return value;
}
export const ParkingLineCanvas = memo(function ParkingLineCanvas({ options, height, label }: { options: Record<string, unknown>; height: number; label: string }) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const subscribe = useCallback((notify: () => void) => subscribeTheme(notify, container), [container]);
  const snapshot = useCallback(() => paletteSnapshot(container), [container]);
  const palette = useSyncExternalStore(subscribe, snapshot, () => "{}");
  const subscribeDimensions = useCallback((notify: () => void) => subscribeSize(notify, container), [container]);
  const sizeSnapshot = useCallback(() => Boolean(container && container.clientWidth > 0 && container.clientHeight > 0), [container]);
  const hasSize = useSyncExternalStore(subscribeDimensions, sizeSnapshot, () => false);
  const chartOptions = useMemo(() => resolveTokens(options, JSON.parse(palette)) as Record<string, unknown>, [options, palette]);
  return <div ref={setContainer} role="img" aria-label={label} style={{ height }}>
    {hasSize ? <EChartsLineChart className={styles.canvas} data={[]} config={config} animation={false} enableHoverHighlight={false} enableHoverReveal={false} chartOptions={chartOptions}>
      <EChartsLineChart.Line dataKey="available" isClickable={false} />
    </EChartsLineChart> : null}
  </div>;
});
