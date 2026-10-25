"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";

import { Alert } from "./ui/alert";
import { Button } from "./ui/button";
import { formatCurrency, formatSeoulDateKey } from "../lib/format";
import type { Airport, FeeCalculationRequest, FeeCalculationResponse } from "../lib/types";

type FeeCalculatorProps = {
  airports: Airport[];
  initialAirportCode: string;
  initialParkingLotId?: number | null;
  onAirportChange?: (code: string) => void;
  onParkingLotChange?: (id: number | null) => void;
  scopeControls?: boolean;
  help?: ReactNode;
  onCalculate: (payload: FeeCalculationRequest) => Promise<FeeCalculationResponse>;
};

function buildDefaultRange() {
  const localDate = formatSeoulDateKey(new Date().toISOString());
  return { entry: `${localDate}T09:00`, exitAt: `${localDate}T15:00` };
}

export function FeeCalculator({ airports, initialAirportCode, initialParkingLotId = null, onAirportChange, onParkingLotChange, scopeControls = true, help, onCalculate }: FeeCalculatorProps) {
  const [defaults] = useState(buildDefaultRange);
  const requestId = useRef(0);
  const [airportCode, setAirportCode] = useState(initialAirportCode);
  const [vehicleSize, setVehicleSize] = useState<"small" | "large">("small");
  const [entryAt, setEntryAt] = useState(defaults.entry);
  const [exitAt, setExitAt] = useState(defaults.exitAt);
  const [parkingLotId, setParkingLotId] = useState<number | null>(null);
  const [result, setResult] = useState<FeeCalculationResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const selectedAirport = airports.find((airport) => airport.code === airportCode);
  const selectableLots = useMemo(() => selectedAirport?.parking_lots.filter((lot) => lot.is_active) ?? [], [selectedAirport]);

  useEffect(() => {
    setAirportCode(initialAirportCode);
  }, [initialAirportCode]);

  useEffect(() => {
    setParkingLotId((current) => selectableLots.some((lot) => lot.id === initialParkingLotId)
      ? initialParkingLotId : scopeControls && selectableLots.some((lot) => lot.id === current) ? current : selectableLots[0]?.id ?? null);
  }, [selectableLots, initialParkingLotId, scopeControls]);


  useEffect(() => {
    requestId.current += 1;
    setPending(false);
    setResult(null);
    setError(null);
  }, [airportCode, parkingLotId, vehicleSize, entryAt, exitAt]);

  useEffect(() => () => { requestId.current += 1; }, []);

  async function handleSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();

    if (!entryAt || !exitAt) {
      setError("입차와 출차 시각을 모두 입력해 주세요.");
      return;
    }

    if (new Date(`${exitAt}:00+09:00`) <= new Date(`${entryAt}:00+09:00`)) {
      setError("출차 시각은 입차 시각보다 늦어야 합니다.");
      return;
    }

    const currentRequest = ++requestId.current;
    setPending(true);
    setResult(null);
    setError(null);

    try {
      const quote = await onCalculate({
        airport_code: airportCode,
        parking_lot_id: parkingLotId,
        vehicle_size: vehicleSize,
        entry_at: new Date(`${entryAt}:00+09:00`).toISOString(),
        exit_at: new Date(`${exitAt}:00+09:00`).toISOString()
      });
      if (currentRequest === requestId.current) setResult(quote);
    } catch (caughtError) {
      if (currentRequest === requestId.current) setError(caughtError instanceof Error ? caughtError.message : "요금 계산에 실패했습니다.");
    } finally {
      if (currentRequest === requestId.current) setPending(false);
    }
  }

  return (
    <section className="panel-surface fee-panel">
      <div className="panel-head">
        <h3>주차요금 계산기{help}</h3>
        <p>공항별 공개 요금 기준 · 입력 시각 KST</p>
      </div>

      <form className="fee-form" onSubmit={handleSubmit}>
        {scopeControls ? <><label className="field">
          <span>공항</span>
          <select className="input" value={airportCode} onChange={(event) => { setAirportCode(event.target.value); onAirportChange?.(event.target.value); }}>
            {airports.map((airport) => (
              <option key={airport.code} value={airport.code}>
                {airport.name_ko}
              </option>
            ))}
          </select>
        </label>

        <label className="field">
          <span>주차장</span>
          <select
            className="input"
            value={parkingLotId ?? ""}
            onChange={(event) => { const next = event.target.value ? Number(event.target.value) : null; setParkingLotId(next); onParkingLotChange?.(next); }}
          >
            {selectableLots.map((lot) => (
              <option key={lot.id} value={lot.id}>
                {lot.name}
              </option>
            ))}
          </select>
        </label></> : null}

        <label className="field">
          <span>차량 크기</span>
          <select
            className="input"
            value={vehicleSize}
            onChange={(event) => setVehicleSize(event.target.value as "small" | "large")}
          >
            <option value="small">소형</option>
            <option value="large">대형</option>
          </select>
        </label>

        <label className="field">
          <span>입차 시각</span>
          <input className="input" type="datetime-local" value={entryAt} onChange={(event) => setEntryAt(event.target.value)} />
        </label>

        <label className="field">
          <span>출차 시각</span>
          <input className="input" type="datetime-local" value={exitAt} onChange={(event) => setExitAt(event.target.value)} />
        </label>

        <Button className="button" disabled={pending || !parkingLotId} type="submit">
          {pending ? "계산 중..." : "요금 계산"}
        </Button>
      </form>
      {!selectableLots.length ? <p className="notice">요금을 계산할 활성 주차장이 없습니다.</p> : null}

      {error ? (
        <Alert className="notice error" variant="destructive">
          {error}
        </Alert>
      ) : null}

      {result ? (
        <div className="quote-box">
          <div className="quote-total">
            <span>예상 요금</span>
            <strong>{result.supported ? formatCurrency(result.total_fee) : result.message ?? "미지원"}</strong>
          </div>
          {result.breakdown.length > 0 ? (
            <ul className="quote-breakdown">
              {result.breakdown.map((line) => (
                <li key={`${line.date}-${line.day_type}`}>
                  <span>
                    {line.date} · {line.day_type === "holiday" ? "휴일" : "평일"} · {line.duration_minutes}분
                  </span>
                  <strong>{formatCurrency(line.applied_fee)}</strong>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}
