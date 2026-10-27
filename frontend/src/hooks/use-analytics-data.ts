"use client";

import { useEffect, useState } from "react";

import { useDashboard } from "../lib/dashboard-context";
import type {
  FlightStatusResponse,
  HolidayPatternResponse,
  ParkingTimeSeriesResponse,
  ThresholdEvent,
  ThresholdInsightsResponse,
  WeekdayHourlyPattern,
} from "../lib/types";

type AnalyticsState = {
  scopeKey: string;
  loading: boolean;
  error: string | null;
  thresholdEvents: ThresholdEvent[];
  thresholdInsights: ThresholdInsightsResponse | null;
  weekdayHourlyPatterns: WeekdayHourlyPattern[];
  holidayPatterns: HolidayPatternResponse | null;
  timeSeries: ParkingTimeSeriesResponse | null;
  flightStatus: FlightStatusResponse | null;
};

const INITIAL_STATE: AnalyticsState = {
  scopeKey: "",
  loading: true,
  error: null,
  thresholdEvents: [],
  thresholdInsights: null,
  weekdayHourlyPatterns: [],
  holidayPatterns: null,
  timeSeries: null,
  flightStatus: null,
};

const FLIGHT_FINAL_TIMEOUT_MS = 30_000;

function buildFlightStatusError(airportCode: string, caughtError: unknown): FlightStatusResponse {
  return {
    generated_at: new Date().toISOString(),
    airport_code: airportCode,
    local_date: new Date().toISOString().slice(0, 10),
    source: "client",
    status: "client_error",
    error_message: caughtError instanceof Error ? caughtError.message : "비행편 정보를 불러오지 못했습니다.",
    items: [],
  };
}

function withTimeout<T>(
  promise: Promise<T>,
  timeoutMs: number,
  buildFallback: () => T,
  onTimeoutId?: (id: ReturnType<typeof setTimeout>) => void
): Promise<T> {
  let timeoutId: ReturnType<typeof setTimeout> | null = null;
  const timeout = new Promise<T>((resolve) => {
    timeoutId = setTimeout(() => resolve(buildFallback()), timeoutMs);
    onTimeoutId?.(timeoutId);
  });

  return Promise.race([
    promise.finally(() => {
      if (timeoutId) {
        clearTimeout(timeoutId);
      }
    }),
    timeout,
  ]);
}

/**
 * Fetches the dashboard analytics bundle (threshold/weekday/holiday/timeseries) plus flight
 * status for the currently-selected airport/lot. Only mounted by routes that need it
 * (/analytics, /history) - this replaces the old IntersectionObserver-gated lazy load with
 * route-mount-gated loading, and re-fetches whenever `dataVersion` bumps (a background poll
 * found new data) even if the airport/lot selection itself hasn't changed.
 */
export function useAnalyticsData(flightStatusTimeoutMs = 6_000, enabled = true): AnalyticsState {
  const { api, selectedAirportCode, selectedParkingLotId, dataVersion, loading: dashboardLoading } = useDashboard();
  const scopeKey = `${selectedAirportCode}/${selectedParkingLotId ?? "all"}`;
  const [state, setState] = useState<AnalyticsState>(INITIAL_STATE);

  useEffect(() => {
    if (!enabled || dashboardLoading || !selectedAirportCode) {
      return;
    }

    let active = true;
    let flightStatusTimeoutId: ReturnType<typeof setTimeout> | null = null;
    let flightFinalTimeoutId: ReturnType<typeof setTimeout> | null = null;
    const flightController = new AbortController();
    let finalFlights: FlightStatusResponse | null = null;
    let analyticsReady = false;
    setState((current) => ({ ...(current.scopeKey === scopeKey ? current : INITIAL_STATE), scopeKey, loading: true, error: null }));

    async function load() {
      try {
        // 6초는 주차 분석을 먼저 여는 안내 시점이다. 같은 요청은 BFF 예산까지
        // 기다리되, 최종 상한 이후 성공이나 폐기된 효과는 화면에 반영하지 않는다.
        const finalFlightRequest = withTimeout(
          api.getFlightStatus(selectedAirportCode, flightController.signal)
            .catch((caughtError) => buildFlightStatusError(selectedAirportCode, caughtError)),
          FLIGHT_FINAL_TIMEOUT_MS,
          () => {
            flightController.abort();
            return buildFlightStatusError(selectedAirportCode, new Error("비행편 정보 조회 시간이 초과됐습니다. 다시 조회해 주세요."));
          },
          (id) => { flightFinalTimeoutId = id; }
        );
        void finalFlightRequest.then((flights) => {
          finalFlights = flights;
          if (!active || !analyticsReady) return;
          setState((current) => current.scopeKey === scopeKey ? { ...current, flightStatus: flights } : current);
        });
        const flightStatusRequest = withTimeout(
          finalFlightRequest,
          flightStatusTimeoutMs,
          () => ({
            ...buildFlightStatusError(selectedAirportCode, new Error("비행편 정보를 계속 조회 중입니다. 도착하면 자동으로 표시합니다.")),
            status: "loading",
          }),
          (id) => {
            flightStatusTimeoutId = id;
          }
        );
        const analyticsRequest = api.getDashboardAnalytics(selectedAirportCode, selectedParkingLotId);
        const [analytics, flights] = await Promise.all([analyticsRequest, flightStatusRequest]);

        if (!active) {
          return;
        }
        analyticsReady = true;
        setState({
          scopeKey,
          loading: false,
          error: null,
          thresholdEvents: analytics.threshold_events,
          thresholdInsights: analytics.threshold_insights,
          weekdayHourlyPatterns: analytics.weekday_hour_patterns,
          holidayPatterns: analytics.holiday_patterns,
          timeSeries: analytics.time_series,
          // 분석이 더 늦게 끝나도 그동안 도착한 실제 항공편을 안내값으로 덮지 않는다.
          flightStatus: finalFlights ?? flights,
        });
      } catch (caughtError) {
        if (!active) {
          return;
        }
        setState((current) => ({
          ...current,
          loading: false,
          error: caughtError instanceof Error ? caughtError.message : "분석 데이터를 불러오지 못했습니다.",
        }));
      }
    }

    void load();
    return () => {
      active = false;
      flightController.abort();
      if (flightStatusTimeoutId) {
        clearTimeout(flightStatusTimeoutId);
      }
      if (flightFinalTimeoutId) {
        clearTimeout(flightFinalTimeoutId);
      }
    };
    // 선택 bootstrap이 완료된 뒤에만 조회하고, 숨은 관리자 탭은 요청하지 않는다.
  }, [api, dataVersion, flightStatusTimeoutMs, enabled, dashboardLoading, selectedAirportCode, selectedParkingLotId, scopeKey]);

  return !dashboardLoading && state.scopeKey === scopeKey ? state : INITIAL_STATE;
}
