"use client";
import { lazy, Suspense } from "react";
import type { ComponentProps } from "react";
import type FuelPriceChart from "./fuel-price-chart";
// 철도·해운도 공유하는 상세 컴포넌트의 초기 경로에서는 ECharts 엔진을 읽지 않는다.
const Chart = lazy(() => import("./fuel-price-chart"));
export default function FuelPriceChartLoader(props: ComponentProps<typeof FuelPriceChart>) {
  return <Suspense fallback={<div className="fuel-echarts" role="group" aria-label={props.label}><p role="status">차트 준비 중…</p></div>}><Chart {...props} /></Suspense>;
}
