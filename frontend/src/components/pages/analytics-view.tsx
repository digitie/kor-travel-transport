"use client";

import { DailyFlightOverlayChart } from "../daily-flight-overlay-chart";
import { Alert } from "../ui/alert";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
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
import type { ThresholdDateHistoryItem } from "../../lib/types";

export function AnalyticsView({ active = true }: { active?: boolean }) {
  const { selectedAirport, selectedParkingLotName, holidaySummary } = useDashboard();
  const { loading, error, thresholdEvents, thresholdInsights, weekdayHourlyPatterns, holidayPatterns, flightStatus, timeSeries } =
    useAnalyticsData(6_000, active);

  const scopeLabel = historyLabel(selectedParkingLotName, selectedAirport?.name_ko);
  const maxHeatValue = Math.max(
    ...weekdayHourlyPatterns.flatMap((pattern) => pattern.hourly_buckets.map((bucket) => bucket.average_available_spaces ?? 0)),
    1
  );
  const thresholdWeekdayItems = thresholdInsights?.weekday_items ?? [];
  const thresholdHistoryItems = thresholdInsights?.history_items ?? [];
  const showThresholdInsights = hasThresholdSamples(thresholdWeekdayItems);
  const averageAvailabilitySummary = summarizeAverageAvailability(weekdayHourlyPatterns);
  const holidayPatternItems = holidayPatterns?.items ?? [];
  const maxHolidayHeatValue = Math.max(
    ...holidayPatternItems.flatMap((pattern) => pattern.hourly_buckets.map((bucket) => bucket.average_available_spaces ?? 0)),
    1
  );

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

        <TabsContent keepMounted value="weekday">
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

                <div className="heatmap-scroll" data-testid="weekday-hour-heatmap">
                  <Table className="heatmap-table">
                    <TableHeader>
                      <TableRow>
                        <TableHead>요일</TableHead>
                        {HOURS.map((hour) => (
                          <TableHead key={`heatmap-hour-${hour}`}>{String(hour).padStart(2, "0")}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {weekdayHourlyPatterns.map((pattern) => (
                        <TableRow key={`heatmap-row-${pattern.weekday}`}>
                          <TableHead>{pattern.weekday_name}</TableHead>
                          {pattern.hourly_buckets.map((bucket) => (
                            <TableCell
                              key={`heatmap-${pattern.weekday}-${bucket.hour}`}
                              data-testid={`weekday-hour-cell-${pattern.weekday}-${bucket.hour}`}
                              style={buildAvailabilityHeatStyle(bucket.average_available_spaces, maxHeatValue)}
                              title={
                                bucket.average_available_spaces === null
                                  ? `${pattern.weekday_name} ${formatHourLabel(bucket.hour)} 관측 없음`
                                  : `${pattern.weekday_name} ${formatHourLabel(bucket.hour)} 평균 ${Math.round(bucket.average_available_spaces)}대`
                              }
                            >
                              {bucket.average_available_spaces === null ? "-" : Math.round(bucket.average_available_spaces)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            )}
          </article>
        </TabsContent>

        <TabsContent keepMounted value="holiday">
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
                <div className="heatmap-scroll" data-testid="holiday-pattern-heatmap">
                  <Table className="heatmap-table holiday-heatmap-table">
                    <TableHeader>
                      <TableRow>
                        <TableHead>특수일</TableHead>
                        {HOURS.map((hour) => (
                          <TableHead key={`holiday-hour-${hour}`}>{String(hour).padStart(2, "0")}</TableHead>
                        ))}
                      </TableRow>
                    </TableHeader>
                    <TableBody>
                      {holidayPatternItems.map((pattern) => (
                        <TableRow key={`holiday-row-${pattern.local_date}-${pattern.name}`}>
                          <TableHead>
                            <strong>{formatHolidayDate(pattern.local_date, pattern.weekday_name)}</strong>
                            <small>{pattern.name}</small>
                          </TableHead>
                          {pattern.hourly_buckets.map((bucket) => (
                            <TableCell
                              key={`holiday-cell-${pattern.local_date}-${bucket.hour}`}
                              data-testid={`holiday-hour-cell-${pattern.local_date}-${bucket.hour}`}
                              style={buildAvailabilityHeatStyle(bucket.average_available_spaces, maxHolidayHeatValue)}
                              title={
                                bucket.average_available_spaces === null
                                  ? `${pattern.name} ${formatHourLabel(bucket.hour)} 관측 없음`
                                  : `${pattern.name} ${formatHourLabel(bucket.hour)} 평균 ${Math.round(bucket.average_available_spaces)}대`
                              }
                            >
                              {bucket.average_available_spaces === null ? "-" : Math.round(bucket.average_available_spaces)}
                            </TableCell>
                          ))}
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </div>
              </>
            )}
          </article>
        </TabsContent>

        <TabsContent keepMounted value="threshold" className="analytics-threshold-panels">
          <article className="panel-surface">
            <div className="panel-head">
              <h3>요일별 임계 달성 시간</h3>
            </div>
            {showThresholdInsights ? (
              <div className="threshold-table-wrap" data-testid="threshold-weekday-grid">
                <Table className="threshold-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>기준</TableHead>
                      {WEEKDAYS.map((weekday) => (
                        <TableHead key={`threshold-weekday-${weekday}`}>{weekday}</TableHead>
                      ))}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {THRESHOLDS.map((threshold) => (
                      <TableRow key={`threshold-row-${threshold}`}>
                        <TableHead>{formatThresholdLabel(threshold)}</TableHead>
                        {WEEKDAYS.map((_, weekday) => {
                          const item = getThresholdWeekdayItem(thresholdWeekdayItems, threshold, weekday);
                          return (
                            <TableCell key={`threshold-cell-${threshold}-${weekday}`}>
                              <strong>{formatMinutesOfDay(item?.typical_minutes_of_day ?? null)}</strong>
                              <small>{item && item.sample_count > 0 ? `${item.sample_count}회` : "기록 없음"}</small>
                            </TableCell>
                          );
                        })}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
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
                <Table className="threshold-history-table">
                  <TableHeader>
                    <TableRow>
                      <TableHead>날짜</TableHead>
                      <TableHead>기준</TableHead>
                      <TableHead>달성 시각</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {thresholdHistoryItems.map((item: ThresholdDateHistoryItem) => (
                      <TableRow key={`${item.threshold}-${item.local_date}-${item.crossed_at}`}>
                        <TableCell>{formatDateCell(item.local_date, item.weekday_name)}</TableCell>
                        <TableCell>{formatThresholdLabel(item.threshold)}</TableCell>
                        <TableCell>
                          {formatMinutesOfDay(item.minutes_of_day)}
                          <small>{formatNumber(item.available_spaces)}대</small>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
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

        <TabsContent keepMounted value="daily">
          {timeSeries || (!loading && !error) ? <DailyFlightOverlayChart flightStatus={flightStatus} holidays={holidaySummary?.items ?? []} series={timeSeries} scopeLabel={scopeLabel} /> : null}
        </TabsContent>
      </Tabs>
    </div>
  );
}
