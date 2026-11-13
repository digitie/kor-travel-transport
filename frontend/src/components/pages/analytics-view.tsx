"use client";

import { ParkingPatternCellDetails, ParkingPatternHeatmap } from "../parking-pattern-heatmap";
import { DailyFlightOverlayChart } from "../daily-flight-overlay-chart";
import { Alert } from "../ui/alert";
import { VirtualTable } from "@kor-travel/ui/virtual-table";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { useAnalyticsData } from "../../hooks/use-analytics-data";
import { useDashboard } from "../../lib/dashboard-context";
import { formatDateTime, formatMinutesOfDay, formatNumber } from "../../lib/format";
import {
  HOURS,
  THRESHOLDS,
  WEEKDAYS,
  buildAvailabilityHeatStyle,
  formatDateCell,
  formatHolidayDate,
  formatHourLabel,
  formatThresholdLabel,
  getThresholdWeekdayItem,
  hasThresholdSamples,
  historyLabel,
  summarizeAverageAvailability,
} from "../../lib/dashboard-view-helpers";

export function AnalyticsView({ active = true }: { active?: boolean }) {
  const { selectedAirport, selectedParkingLotName, holidaySummary } = useDashboard();
  const data = useAnalyticsData(6_000, active);
  const { loading, error, flightStatus, timeSeries } = data;
  const scopeLabel = historyLabel(selectedParkingLotName, selectedAirport?.name_ko);

  return (
    <div className="page-shell">
      <header className="page-header">
        <h2>분석</h2>
      </header>

      {error ? (
        <Alert className="notice error" variant="destructive">
          {error}
        </Alert>
      ) : null}
      {loading ? <p className="notice" role="status">분석 자료를 불러오는 중입니다.</p> : null}

      <Tabs defaultValue="weekday" className="analytics-tabs" aria-busy={loading}>
        <TabsList variant="line">
          <TabsTrigger value="weekday">요일별 패턴</TabsTrigger>
          <TabsTrigger value="holiday">공휴일 패턴</TabsTrigger>
          <TabsTrigger value="threshold">임계치</TabsTrigger>
          <TabsTrigger value="daily">일별 흐름</TabsTrigger>
        </TabsList>

        <WeekdayPanel data={data} scopeLabel={scopeLabel} />

        <HolidayPanel data={data} scopeLabel={scopeLabel} />

        <ThresholdPanel data={data} scopeLabel={scopeLabel} />

        <TabsContent forceMount value="daily" className="data-[state=inactive]:hidden">
          {timeSeries || (!loading && !error) ? <DailyFlightOverlayChart flightStatus={flightStatus} holidays={holidaySummary?.items ?? []} series={timeSeries} scopeLabel={scopeLabel} /> : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}

type AnalyticsPanelProps = { data: ReturnType<typeof useAnalyticsData>; scopeLabel: string };

function WeekdayPanel({ data }: AnalyticsPanelProps) {
  const { loading, error, weekdayHourlyPatterns } = data;
  const averageAvailabilitySummary = summarizeAverageAvailability(weekdayHourlyPatterns);
  const maxHeatValue = Math.max(...weekdayHourlyPatterns.flatMap((pattern) => pattern.hourly_buckets.map((bucket) => bucket.average_available_spaces ?? 0)), 1);
  return (
        <TabsContent forceMount value="weekday" className="data-[state=inactive]:hidden">
          <article className="panel-surface panel-full-span">
            <div className="panel-head">
              <h3>요일별 시간대 평균 잔여 주차면</h3>
            </div>
            {weekdayHourlyPatterns.length === 0 ? (
              !loading && !error ? <p className="notice">표시할 요일별 시간대 데이터가 없습니다.</p> : null
            ) : (
              <>
                <div className="pattern-summary-lines">
                  <span>
                    <strong>최고 혼잡</strong> :{" "}
                    {averageAvailabilitySummary.tightest
                      ? `${averageAvailabilitySummary.tightest.weekdayName} ${formatHourLabel(averageAvailabilitySummary.tightest.hour)} 평균 ${formatNumber(Math.round(averageAvailabilitySummary.tightest.value))}대`
                      : "데이터 없음"}
                  </span>
                  <span>
                    <strong>최저 혼잡</strong> :{" "}
                    {averageAvailabilitySummary.roomiest
                      ? `${averageAvailabilitySummary.roomiest.weekdayName} ${formatHourLabel(averageAvailabilitySummary.roomiest.hour)} 평균 ${formatNumber(Math.round(averageAvailabilitySummary.roomiest.value))}대`
                      : "데이터 없음"}
                  </span>
                </div>

                <ParkingPatternHeatmap rows={weekdayHourlyPatterns.map((row) => ({ key: String(row.weekday), label: row.weekday_name, hourly_buckets: row.hourly_buckets }))} />
                <details><summary>시간대별 수치 표</summary>
                <div className="heatmap-scroll" data-testid="weekday-hour-heatmap">
                  <VirtualTable ariaLabel="요일별 시간대 잔여 주차면" containerClassName="heatmap-table" data={weekdayHourlyPatterns} getRowId={(pattern) => String(pattern.weekday)} virtualized={false} columns={[
                    { id: 'label', header: '요일', cell: ({ row: { original: pattern } }) => <>{pattern.weekday_name}</> },
                    ...HOURS.map((hour) => ({ id: `hour-${hour}`, header: String(hour).padStart(2, '0'),
                      cell: ({ row: { original: pattern } }: { row: { original: (typeof weekdayHourlyPatterns)[number] } }) => {
                        const bucket = pattern.hourly_buckets.find((item) => item.hour === hour);
                        const value = bucket?.average_available_spaces ?? null;
                        return <div data-testid={`weekday-hour-cell-${pattern.weekday}-${hour}`} style={buildAvailabilityHeatStyle(value, maxHeatValue)}
                          title={value === null ? `${pattern.weekday_name} ${formatHourLabel(hour)} 관측 없음` : `${pattern.weekday_name} ${formatHourLabel(hour)} 평균 ${value}대`}>
                          <ParkingPatternCellDetails label={pattern.weekday_name} bucket={bucket} /></div>;
                      } })),
                  ]} />
                </div>
                </details>
              </>
            )}
          </article>
        </TabsContent>
  );
}

function HolidayPanel({ data }: AnalyticsPanelProps) {
  const { loading, error, holidayPatterns } = data;
  const holidayPatternItems = holidayPatterns?.items ?? [];
  const maxHolidayHeatValue = Math.max(...holidayPatternItems.flatMap((pattern) => pattern.hourly_buckets.map((bucket) => bucket.average_available_spaces ?? 0)), 1);
  return (
        <TabsContent forceMount value="holiday" className="data-[state=inactive]:hidden">
          <article className="panel-surface panel-full-span">
            <div className="panel-head">
              <div>
                <h3>공휴일/토/일요일 패턴</h3>
                <p>최근 공휴일/토/일요일 날짜별 시간대 잔여 주차면</p>
              </div>
            </div>
            {holidayPatternItems.length === 0 ? (
              !loading && !error ? <p className="notice">표시할 공휴일/토/일요일 패턴 데이터가 없습니다.</p> : null
            ) : (
              <>
                {holidayPatterns?.error_message ? <p className="notice error">{holidayPatterns.error_message}</p> : null}
                <ParkingPatternHeatmap rows={holidayPatternItems.map((row) => ({ key: `${row.local_date}-${row.name}`, label: `${row.local_date} ${row.name}`, hourly_buckets: row.hourly_buckets }))} />
                <details><summary>특수일별 수치 표</summary>
                <div className="heatmap-scroll" data-testid="holiday-pattern-heatmap">
                  <VirtualTable ariaLabel="특수일별 시간대 잔여 주차면" containerClassName="heatmap-table holiday-heatmap-table" data={holidayPatternItems} getRowId={(pattern) => `${pattern.local_date}-${pattern.name}`} virtualized={false} columns={[
                    { id: 'label', header: '특수일', cell: ({ row: { original: pattern } }) => <><strong>{formatHolidayDate(pattern.local_date, pattern.weekday_name)}</strong><small>{pattern.name}</small></> },
                    ...HOURS.map((hour) => ({ id: `hour-${hour}`, header: String(hour).padStart(2, '0'),
                      cell: ({ row: { original: pattern } }: { row: { original: (typeof holidayPatternItems)[number] } }) => {
                        const bucket = pattern.hourly_buckets.find((item) => item.hour === hour);
                        const value = bucket?.average_available_spaces ?? null;
                        return <div data-testid={`holiday-hour-cell-${pattern.local_date}-${hour}`} style={buildAvailabilityHeatStyle(value, maxHolidayHeatValue)}
                          title={value === null ? `${pattern.name} ${formatHourLabel(hour)} 관측 없음` : `${pattern.name} ${formatHourLabel(hour)} 평균 ${value}대`}>
                          <ParkingPatternCellDetails label={`${pattern.local_date} ${pattern.name}`} bucket={bucket} /></div>;
                      } })),
                  ]} />
                </div>
                </details>
              </>
            )}
          </article>
        </TabsContent>
  );
}

function ThresholdPanel({ data }: AnalyticsPanelProps) {
  const { loading, error, thresholdEvents, thresholdInsights } = data;
  const thresholdWeekdayItems = thresholdInsights?.weekday_items ?? [];
  const thresholdHistoryItems = thresholdInsights?.history_items ?? [];
  const showThresholdInsights = hasThresholdSamples(thresholdWeekdayItems);
  return (
        <TabsContent forceMount value="threshold" className="data-[state=inactive]:hidden analytics-threshold-panels">
          <article className="panel-surface">
            <div className="panel-head">
              <h3>요일별 임계 달성 시간</h3>
            </div>
            {showThresholdInsights ? (
              <div className="threshold-table-wrap" data-testid="threshold-weekday-grid">
                <VirtualTable ariaLabel="요일별 임계 달성 시간" containerClassName="threshold-table" data={THRESHOLDS.map((threshold) => ({ threshold }))} getRowId={(row) => String(row.threshold)} virtualized={false} columns={[
                  { id: 'threshold', header: '기준', cell: ({ row }) => formatThresholdLabel(row.original.threshold) },
                  ...WEEKDAYS.map((label, weekday) => ({ id: `day-${weekday}`, header: label,
                    cell: ({ row }: { row: { original: { threshold: (typeof THRESHOLDS)[number] } } }) => {
                      const item = getThresholdWeekdayItem(thresholdWeekdayItems, row.original.threshold, weekday);
                      return <><strong>{formatMinutesOfDay(item?.typical_minutes_of_day ?? null)}</strong><small>{item && item.sample_count > 0 ? `${item.sample_count}회` : '기록 없음'}</small></>;
                    } })),
                ]} />
              </div>
            ) : (
              !loading && !error ? <p className="notice">임계 달성 시각을 계산할 만큼 충분한 기록이 없습니다.</p> : null
            )}
          </article>

          <article className="panel-surface">
            <div className="panel-head">
              <h3>날짜별 임계 달성 시간</h3>
            </div>
            {thresholdHistoryItems.length > 0 ? (
              <div className="threshold-scroll" data-testid="threshold-history-scroll">
                <VirtualTable ariaLabel="날짜별 임계 달성 시간" containerClassName="threshold-history-table" data={thresholdHistoryItems}
                  getRowId={(item) => `${item.threshold}-${item.local_date}-${item.crossed_at}`} virtualized={false} columns={[
                    { id: 'date', header: '날짜', cell: ({ row }) => formatDateCell(row.original.local_date, row.original.weekday_name) },
                    { id: 'threshold', header: '기준', cell: ({ row }) => formatThresholdLabel(row.original.threshold) },
                    { id: 'time', header: '달성 시각', cell: ({ row }) => <>{formatMinutesOfDay(row.original.minutes_of_day)}<small>{formatNumber(row.original.available_spaces)}대</small></> },
                  ]} />
              </div>
            ) : (
              !loading && !error ? <p className="notice">최근 기준에서 임계 달성 기록이 없습니다.</p> : null
            )}
          </article>

          <article className="panel-surface panel-full-span threshold-panel">
            <div className="panel-head">
              <h3>임계치 이벤트</h3>
            </div>
            {thresholdEvents.length === 0 ? (
              !loading && !error ? <p className="notice">선택한 기준에서 최근 임계치 이벤트가 없습니다.</p> : null
            ) : (
              <div className="threshold-scroll" data-testid="threshold-events-scroll">
                <ul className="threshold-list">
                  {thresholdEvents.map((event) => (
                    <li key={`${event.parking_lot_id}-${event.threshold}-${event.crossed_at}-${event.direction}`}>
                      <div>
                        <strong>{event.parking_lot_name}</strong>
                        <span>{formatDateTime(event.crossed_at)}</span>
                      </div>
                      <p>
                        {formatNumber(event.threshold)}대{" "}
                        {event.direction === "down" ? "미만 진입" : "이상 회복"}:{" "}
                        {formatNumber(event.previous_available_spaces)}대에서{" "}
                        {formatNumber(event.current_available_spaces)}대로 변했습니다.
                      </p>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </article>
        </TabsContent>
  );
}
