import { withAlpha } from "./evilcharts/ui/echarts-chart";
import { escapeTooltipHtml as escapeHtml } from "./evilcharts/ui/echarts-tooltip";
import {
  binLabel, histogramValues, pinnedPercent, priceAxisRange, won,
  type FuelPriceScope, type FuelSigunguDistribution,
} from "@/lib/fuel-price-distribution";

// 선(가격 곡선)=warning(주황), 막대=text-secondary(회색), 전국 최저/평균/최고=brand/success/danger.
export const CHART_TOKENS = ["--warning", "--text-secondary", "--brand", "--success", "--danger", "--card", "--text-primary", "--control-line"] as const;
export type ChartPalette = Record<(typeof CHART_TOKENS)[number], string>;

export type FuelDistributionChartProps = {
  distribution: FuelSigunguDistribution;
  nationwide: FuelPriceScope | null;
  productLabel: string;
  percent: boolean;
  compare: boolean;
  pinnedPrice?: number | null;
  label: string;
};

/** 시군구 가격 분포 ECharts 옵션(순수 함수). */
export function distributionOption({ distribution, nationwide, productLabel, percent, compare, pinnedPrice, palette }: Omit<FuelDistributionChartProps, "label"> & { palette: ChartPalette }) {
  const counts = histogramValues(distribution, percent);
  const range = priceAxisRange(distribution, nationwide, compare, pinnedPrice);
  const line = palette["--warning"], muted = palette["--text-secondary"];
  const national = compare && nationwide ? [
    { name: "전국 최저", value: nationwide.minimum_price, color: palette["--brand"] },
    { name: "전국 평균", value: nationwide.average_price, color: palette["--success"] },
    { name: "전국 최고", value: nationwide.maximum_price, color: palette["--danger"] },
  ] : [];
  const pinX = pinnedPrice != null ? pinnedPercent(distribution, pinnedPrice) : null;
  const tooltip = (parameter: { seriesType?: string; dataIndex?: number; value?: unknown }) => {
    if (parameter.seriesType === "bar" && parameter.dataIndex != null) {
      const bin = distribution.histogram[parameter.dataIndex];
      return `<strong>${escapeHtml(binLabel(bin.start))}</strong> ${escapeHtml(percent ? `${counts[parameter.dataIndex]}%` : `${bin.count}개`)}`;
    }
    if (Array.isArray(parameter.value)) {
      const [position, price] = parameter.value as [number, number];
      return `낮은 가격부터 ${escapeHtml(String(Math.round(position)))}% · <strong>${escapeHtml(won(price))}</strong>`;
    }
    return "";
  };
  return {
    animation: false,
    grid: { left: 58, right: 40, top: 16, bottom: 26, containLabel: false },
    tooltip: {
      trigger: "item", triggerOn: "mousemove|click", confine: true, formatter: tooltip,
      backgroundColor: palette["--card"], borderColor: palette["--control-line"], textStyle: { color: palette["--text-primary"] },
    },
    xAxis: [
      { type: "category", data: distribution.histogram.map(bin => Math.round(bin.start).toLocaleString("ko-KR")),
        axisLabel: { color: muted, hideOverlap: true, fontSize: 10 }, axisTick: { alignWithLabel: false }, axisLine: { lineStyle: { color: muted } } },
      // 가격 곡선은 "낮은 가격부터의 위치(0~100%)"를 가로축으로 쓴다. 막대의 가격 구간 축과 겹쳐 그리되 눈금은 숨긴다.
      { type: "value", min: 0, max: 100, show: false },
    ],
    yAxis: [
      { type: "value", min: range.min, max: range.max, interval: range.interval,
        axisLabel: { color: muted, fontSize: 10, formatter: (value: number) => `${value.toLocaleString("ko-KR")}원` },
        splitLine: { lineStyle: { color: withAlpha(muted, .25) } } },
      { type: "value", min: 0, position: "right", minInterval: 1, splitLine: { show: false },
        axisLabel: { color: muted, fontSize: 10, formatter: (value: number) => percent ? `${value}%` : `${value}개` } },
    ],
    series: [
      { type: "bar", name: "가격 분포", xAxisIndex: 0, yAxisIndex: 1, data: counts, barCategoryGap: "4%",
        itemStyle: { color: withAlpha(muted, .55), borderColor: withAlpha(muted, .9), borderWidth: 1 }, z: 1 },
      { type: "line", name: `${productLabel} 가격`, xAxisIndex: 1, yAxisIndex: 0, z: 3,
        data: distribution.quantiles.map(point => [point.percent, point.price]),
        lineStyle: { color: line, width: 2.5 }, itemStyle: { color: line }, symbol: "circle", symbolSize: 7,
        markLine: national.length ? {
          silent: true, symbol: "none", label: { show: false },
          data: national.map(row => ({ name: row.name, yAxis: row.value, lineStyle: { color: row.color, type: "dashed", width: 1.5 } })),
        } : undefined,
        markPoint: pinX != null && pinnedPrice != null ? {
          symbol: "pin", symbolSize: 34, silent: true,
          itemStyle: { color: palette["--text-primary"] },
          label: { show: false },
          data: [{ name: "이 주유소", coord: [pinX, pinnedPrice] }],
        } : undefined },
    ],
  };
}
