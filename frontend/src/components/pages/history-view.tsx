"use client";

import { differenceInCalendarDays } from "date-fns";
import { ko } from "date-fns/locale";
import { useEffect, useRef, useState } from "react";
import type { DateRange } from "react-day-picker";

import { HistoryChart } from "../history-chart";
import { Alert } from "../ui/alert";
import { Button } from "../ui/button";
import { Calendar } from "../ui/calendar";
import { Card } from "../ui/card";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "../ui/popover";
import { useDashboard } from "../../lib/dashboard-context";
import { historyLabel, summarizeTimeSeriesAvailability } from "../../lib/dashboard-view-helpers";
import { seoulDateBoundary, toDateKey } from "../../lib/format";
import type { ParkingTimeSeriesResponse } from "../../lib/types";

const DEFAULT_RELATIVE_DAYS = 7;

function formatRangeLabel(range: DateRange | undefined): string {
  if (!range?.from) {
    return "날짜 범위 선택";
  }
  if (!range.to) {
    return `${toDateKey(range.from)} ~ 종료일 선택`;
  }
  return `${toDateKey(range.from)} ~ ${toDateKey(range.to)}`;
}

/** Coarsens the bucket interval as the requested span grows, so a multi-week lookup
 * doesn't request tens of thousands of 10-minute buckets in one response/chart render. */
function pickIntervalMinutes(from: Date, to: Date): number {
  const spanDays = differenceInCalendarDays(to, from) + 1;
  if (spanDays <= 3) {
    return 10;
  }
  if (spanDays <= 14) {
    return 30;
  }
  return 60;
}

export function HistoryView({ active = true }: { active?: boolean }) {
  const {
    api,
    selectedAirportCode,
    selectedParkingLotId,
    selectedAirport,
    selectedParkingLotName,
    holidaySummary,
    collectorStatus,
    dataVersion,
    loading: dashboardLoading,
  } = useDashboard();
  const [range, setRange] = useState<DateRange | undefined>(undefined);
  const [timeSeries, setTimeSeries] = useState<ParkingTimeSeriesResponse | null>(null);
  const [seriesScope, setSeriesScope] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);

  const scopeLabel = historyLabel(selectedParkingLotName, selectedAirport?.name_ko);
  // Both bounds must be read as Asia/Seoul calendar days, not the viewer's own timezone -
  // the calendar's day cells are browser-local Dates, so comparing them against a bound
  // built from a raw UTC instant (or the browser's own "now") can be off by a day for any
  // viewer not in KST.
  const earliestSelectable = collectorStatus?.earliest_snapshot_observed_at
    ? seoulDateBoundary(collectorStatus.earliest_snapshot_observed_at)
    : undefined;
  const today = seoulDateBoundary(new Date().toISOString());
  const hasCustomRange = Boolean(range?.from && range?.to);
  const scopeKey = `${selectedAirportCode}/${selectedParkingLotId ?? "all"}/${range?.from && range?.to ? `${toDateKey(range.from)}/${toDateKey(range.to)}` : "7d"}`;
  const visibleSeries = !dashboardLoading && seriesScope === scopeKey ? timeSeries : null;

  useEffect(() => {
    if (!active || dashboardLoading || !selectedAirportCode) {
      return;
    }

    let requestActive = true;
    setLoading(true);
    setError(null);

    const request =
      range?.from && range?.to
        ? api.getTimeSeries(selectedAirportCode, {
            parkingLotId: selectedParkingLotId,
            startDate: toDateKey(range.from),
            endDate: toDateKey(range.to),
            intervalMinutes: pickIntervalMinutes(range.from, range.to),
          })
        : api.getTimeSeries(selectedAirportCode, { parkingLotId: selectedParkingLotId, days: DEFAULT_RELATIVE_DAYS });

    request
      .then((response) => {
        if (!requestActive) {
          return;
        }
        setTimeSeries(response);
        setSeriesScope(scopeKey);
        setLoading(false);
      })
      .catch((caughtError) => {
        if (!requestActive) {
          return;
        }
        setError(caughtError instanceof Error ? caughtError.message : "과거 자료를 불러오지 못했습니다.");
        setLoading(false);
      });

    return () => {
      requestActive = false;
    };
    // range is read directly (not spread into primitives) - a new Date selection always
    // produces a new object, so this effect re-runs exactly when the user picks a new range.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [api, selectedAirportCode, selectedParkingLotId, dataVersion, range, active, dashboardLoading, scopeKey]);

  const summary = visibleSeries ? summarizeTimeSeriesAvailability(visibleSeries.items) : null;

  function resetToRelativeWindow() {
    setRange(undefined);
    // The button being clicked disappears once hasCustomRange flips to false - move focus
    // back to the picker trigger instead of letting it fall through to <body>.
    triggerRef.current?.focus();
  }

  return (
    <div className="page-shell">
      <header className="page-header">
        <h2>과거 자료 조회</h2>
      </header>

      <div className="action-stack">
        <Popover>
          <PopoverTrigger ref={triggerRef} className="button secondary" type="button">
            {formatRangeLabel(range)}
          </PopoverTrigger>
          <PopoverContent className="w-auto p-0" align="start">
            <PopoverTitle className="sr-only">조회할 날짜 범위 선택</PopoverTitle>
            <Calendar
              mode="range"
              locale={ko}
              selected={range}
              onSelect={setRange}
              defaultMonth={range?.from ?? earliestSelectable}
              disabled={[
                ...(earliestSelectable ? [{ before: earliestSelectable }] : []),
                { after: today },
              ]}
              numberOfMonths={1}
            />
          </PopoverContent>
        </Popover>
        {hasCustomRange ? (
          <Button className="button secondary" variant="secondary" type="button" onClick={resetToRelativeWindow}>
            최근 {DEFAULT_RELATIVE_DAYS}일 보기
          </Button>
        ) : null}
      </div>

      {/* T-038 Hallmark audit: a screen reader is not guaranteed to announce a live
          region that arrives already-mounted with its final content - keep this
          announcer permanently mounted and let only its content change. */}
      <p className="sr-only" aria-live="polite">
        {loading ? "데이터를 불러오는 중입니다." : ""}
      </p>

      {error ? (
        <Alert className="notice error" variant="destructive">
          {error}
        </Alert>
      ) : null}
      {loading ? (
        <p className="notice" aria-hidden="true">
          데이터를 불러오는 중입니다.
        </p>
      ) : null}

      {summary && (summary.min !== null || summary.max !== null || summary.average !== null) ? (
        <section className="detail-ribbon">
          <Card className="metric-card detail-card">
            <span>최소 잔여 주차면</span>
            <strong>{summary.min}대</strong>
          </Card>
          <Card className="metric-card detail-card">
            <span>평균 잔여 주차면</span>
            <strong>{summary.average}대</strong>
          </Card>
          <Card className="metric-card detail-card">
            <span>최대 잔여 주차면</span>
            <strong>{summary.max}대</strong>
          </Card>
        </section>
      ) : null}

      {visibleSeries || (!loading && !error) ? <HistoryChart holidays={holidaySummary?.items ?? []} series={visibleSeries} scopeLabel={scopeLabel} /> : null}
    </div>
  );
}
