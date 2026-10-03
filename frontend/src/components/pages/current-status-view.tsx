"use client";

import { Alert } from "@/components/ui/alert";
import { Card } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { useDashboard } from "@/lib/dashboard-context";
import { formatDateTime, formatNumber } from "@/lib/format";
import { statusLabel, statusTone } from "@/lib/dashboard-view-helpers";

function findLatestValue<T extends { observed_at: string }>(items: T[]): string | null {
  if (items.length === 0) {
    return null;
  }
  return items.reduce<string | null>((latest, item) => {
    if (latest === null) {
      return item.observed_at;
    }
    return Date.parse(item.observed_at) > Date.parse(latest) ? item.observed_at : latest;
  }, null);
}

export function CurrentStatusView() {
  const {
    selectedAirport,
    selectedParkingLotId,
    selectedParkingLotName,
    scopeItems,
    holidaySummary,
    loading,
    error,
  } = useDashboard();

  const latestObservedAt = findLatestValue(scopeItems);
  const sortedByAvailable = [...scopeItems].sort((left, right) => left.available_spaces - right.available_spaces);
  const tightestLot = sortedByAvailable[0];
  const roomiestLot = sortedByAvailable[sortedByAvailable.length - 1];
  const totalAvailableSpaces = scopeItems.reduce((sum, item) => sum + item.available_spaces, 0);
  const totalOccupiedSpaces = scopeItems.reduce((sum, item) => sum + item.occupied_spaces, 0);
  const totalSpaces = scopeItems.reduce((sum, item) => sum + item.total_spaces, 0);
  const focusedLot = selectedParkingLotId !== null ? scopeItems[0] ?? null : null;

  return (
    <div className="page-shell">
      <section className="status-header">
        <div>
          <h2>{selectedAirport?.name_ko ?? "공항"}</h2>
          <div className="status-meta">
            <span>데이터 기준 시각: {latestObservedAt ? formatDateTime(latestObservedAt) : "데이터 없음"}</span>
            {holidaySummary ? <span className="holiday-sentence">{holidaySummary.sentence}</span> : null}
          </div>
        </div>
      </section>

      <section className="detail-ribbon">
        <Card className="metric-card detail-card">
          <span>현재 잔여 주차면</span>
          <strong>{formatNumber(totalAvailableSpaces)}대</strong>
          <small>{selectedParkingLotName ? "선택 주차장 기준" : "공항 합산 기준"}</small>
        </Card>

        <Card className="metric-card detail-card">
          <span>{focusedLot ? "현재 상태" : "가장 빠듯한 곳"}</span>
          <strong>{focusedLot ? statusLabel(focusedLot.status_level) : tightestLot?.parking_lot_name ?? "-"}</strong>
          <small>
            {focusedLot
              ? `${formatNumber(focusedLot.available_spaces)}대 남음`
              : tightestLot
                ? `${formatNumber(tightestLot.available_spaces)}대 남음`
                : "데이터 없음"}
          </small>
        </Card>

        <Card className="metric-card detail-card">
          <span>{focusedLot ? "전체 주차면" : "가장 여유 있는 곳"}</span>
          <strong>{focusedLot ? `${formatNumber(totalSpaces)}대` : roomiestLot?.parking_lot_name ?? "-"}</strong>
          <small>
            {focusedLot
              ? `점유 ${formatNumber(totalOccupiedSpaces)} / 전체 ${formatNumber(totalSpaces)}`
              : roomiestLot
                ? `${formatNumber(roomiestLot.available_spaces)}대 남음`
                : "데이터 없음"}
          </small>
        </Card>
      </section>

      {/* T-038 Hallmark audit: a screen reader is not guaranteed to announce a live
          region that arrives already-mounted with its final content - the region
          must exist first, then have its content change. This announcer stays
          permanently mounted (empty text = nothing announced). */}
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

      <div className="hidden lg:block">
        <section className="table-surface" data-testid="desktop-lot-table">
          <Table className="lot-table">
            <TableHeader>
              <TableRow>
                <TableHead>주차장</TableHead>
                <TableHead>잔여/전체</TableHead>
                <TableHead>기준 시각</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {scopeItems.map((item) => (
                <TableRow key={item.parking_lot_id}>
                  <TableCell>
                    <strong>{item.parking_lot_name}</strong>
                    <span>{item.terminal ?? "터미널 정보 없음"}</span>
                  </TableCell>
                  <TableCell>
                    {formatNumber(item.available_spaces)}/{formatNumber(item.total_spaces)}대
                  </TableCell>
                  <TableCell>{formatDateTime(item.observed_at)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </section>
      </div>

      {/* `lg:hidden` intentionally omitted here - it has no effect on `.lot-card-grid`
          (a plain custom class beats any Tailwind utility regardless of breakpoint,
          see globals.css T-039 comment). The CSS media query on `.lot-card-grid`
          itself is what actually hides this on desktop. */}
      <section className="lot-card-grid" data-testid="mobile-lot-grid">
        {scopeItems.map((item) => (
          <article key={item.parking_lot_id} className={`lot-card ${statusTone(item.status_level)}`}>
            <div className="lot-card-top">
              <div>
                <h3>{item.parking_lot_name}</h3>
                <p>{item.terminal ?? "터미널 정보 없음"}</p>
              </div>
            </div>
            <div className="lot-card-stats">
              <div>
                <span>잔여/전체</span>
                <strong>
                  {formatNumber(item.available_spaces)}/{formatNumber(item.total_spaces)}대
                </strong>
              </div>
            </div>
            <p className="stamp">기준 시각 {formatDateTime(item.observed_at)}</p>
          </article>
        ))}
      </section>

      {scopeItems.length === 0 ? <p className="notice">조건에 맞는 주차장이 없습니다.</p> : null}
    </div>
  );
}
