"use client";

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useForm, useWatch } from "react-hook-form";
import { z } from "zod";
import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";
import { Info } from "lucide-react";

import { Alert } from "./ui/alert";
import { Button } from "./ui/button";
import { Popover, PopoverContent, PopoverTitle, PopoverTrigger } from "./ui/popover";
import { formatCurrency, formatDateTimeWithZone, formatSeoulDateKey } from "../lib/format";
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
  const { timeForm, handleSubmit, airportCode, setAirportCode, parkingLotId, setParkingLotId, selectableLots, vehicleSize, setVehicleSize, pending, error, result } = useFeeCalculatorSelection({ airports, initialAirportCode, initialParkingLotId, onAirportChange, onParkingLotChange, scopeControls, help, onCalculate });
  return (
    <section className="panel-surface fee-panel">
      <div className="panel-head">
        <h3>주차요금 계산기{help ?? <Popover>
          <PopoverTrigger asChild><Button variant="ghost" size="icon-xs" aria-label="주차요금 계산 안내"><Info /></Button></PopoverTrigger>
          <PopoverContent><PopoverTitle>주차요금 계산 안내</PopoverTitle><p>입출차 시각은 한국 시간입니다. 선택한 주차장·차량의 저장 규칙으로 일반요금을 계산하며, 증빙이 필요한 할인은 반영하지 않습니다.</p></PopoverContent>
        </Popover>}</h3>
      </div>

      <form className="fee-form" onSubmit={timeForm.handleSubmit(handleSubmit)}>
        {scopeControls ? <><FeeAirportSelect airportCode={airportCode} setAirportCode={setAirportCode} onAirportChange={onAirportChange} airports={airports} />

        <FeeParkingSelect parkingLotId={parkingLotId} setParkingLotId={setParkingLotId} onParkingLotChange={onParkingLotChange} selectableLots={selectableLots} /></> : null}

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
          <input className="input" type="datetime-local" {...timeForm.register("entryAt")} />
        </label>

        <label className="field">
          <span>출차 시각</span>
          <input className="input" type="datetime-local" {...timeForm.register("exitAt")} />
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
        <FeeQuote result={result} />
      ) : null}
    </section>
  );
}

function FeeQuote({ result }: { result: FeeCalculationResponse }) {
  return (
        <div className="quote-box">
          <div className="quote-total">
            <span>예상 요금{result.supported ? <Popover>
              <PopoverTrigger asChild><Button variant="ghost" size="icon-xs" aria-label="계산 근거와 공식 요금 안내"><Info /></Button></PopoverTrigger>
              <PopoverContent>
                <PopoverTitle>계산 근거</PopoverTitle>
                {result.message ? <p>{result.message}</p> : null}
                {result.rule_updated_at ? <p>규칙 확인 {formatDateTimeWithZone(result.rule_updated_at)}</p> : null}
                {result.official_url ? <a href={result.official_url} target="_blank" rel="noreferrer">공항 공식 요금 안내 ↗</a> : null}
              </PopoverContent>
            </Popover> : null}</span>
            <strong>{result.supported ? formatCurrency(result.total_fee) : "계산 불가"}</strong>
          </div>
          {!result.supported ? <div role="status">
            <p>{result.message ?? "선택한 주차장·차량의 요금 규칙을 확인할 수 없습니다."}</p>
            {result.official_url ? <a href={result.official_url} target="_blank" rel="noreferrer">공항 공식 요금 안내 ↗</a> : null}
          </div> : null}
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
  );
}

type FeeQuoteInput = { airportCode: string; parkingLotId: number | null; vehicleSize: "small" | "large"; entryAt?: string; exitAt?: string; onCalculate: FeeCalculatorProps["onCalculate"] };
function useFeeQuote({ airportCode, parkingLotId, vehicleSize, entryAt, exitAt, onCalculate }: FeeQuoteInput) {
  const requestId = useRef(0);
  const inputKey = JSON.stringify([airportCode, parkingLotId, vehicleSize, entryAt, exitAt]);
  const [quoteStore] = useState(() => createStore<{
    scope: string; result: FeeCalculationResponse | null; error: string | null; pending: boolean;
  }>(() => ({ scope: "", result: null, error: null, pending: false })));
  const quote = useStore(quoteStore);
  const result = quote.scope === inputKey ? quote.result : null;
  const error = quote.scope === inputKey ? quote.error : null;
  const pending = quote.scope === inputKey && quote.pending;
  const updateQuote = useCallback((patch: Partial<Omit<typeof quote, "scope">>) => {
    quoteStore.setState((current) => ({
      ...(current.scope === inputKey ? current : { result: null, error: null, pending: false }),
      ...patch, scope: inputKey,
    }));
  }, [inputKey, quoteStore]);
  const setResult = (result: FeeCalculationResponse | null) => updateQuote({ result });
  const setError = (error: string | null) => updateQuote({ error });
  const setPending = (pending: boolean) => updateQuote({ pending });
  // 입력 정체가 달라지면 이전 요청의 결과를 버린다. 화면 초기화는 위의 scope 비교에서 파생한다.
  useEffect(() => { requestId.current += 1; }, [inputKey]);

  useEffect(() => () => { requestId.current += 1; }, []);

  async function handleSubmit() {

    if (!z.object({ entryAt: z.string().min(1), exitAt: z.string().min(1) }).safeParse({ entryAt, exitAt }).success || !entryAt || !exitAt) {
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

  return { result, error, pending, handleSubmit };
}


// 조회·선택·요청 수명은 이 도메인 훅이, 아래 컴포넌트는 표현을 소유한다.
function useFeeCalculatorSelection({ airports, initialAirportCode, initialParkingLotId = null, scopeControls = true, onCalculate }: FeeCalculatorProps) {
  const [defaults] = useState(buildDefaultRange);
  const [airportSelection, setAirportSelection] = useState({ initial: initialAirportCode, value: initialAirportCode });
  const airportCode = airportSelection.initial === initialAirportCode ? airportSelection.value : initialAirportCode;
  const setAirportCode = (value: string) => setAirportSelection({ initial: initialAirportCode, value });
  const [vehicleSize, setVehicleSize] = useState<"small" | "large">("small");
  const timeForm = useForm<{ entryAt: string; exitAt: string }>({ defaultValues: { entryAt: defaults.entry, exitAt: defaults.exitAt } });
  const { entryAt, exitAt } = useWatch({ control: timeForm.control });
  const [parkingSelection, setParkingSelection] = useState({ airportCode: initialAirportCode, initialParkingLotId, value: null as number | null });

  const selectedAirport = airports.find((airport) => airport.code === airportCode);
  const selectableLots = useMemo(() => selectedAirport?.parking_lots.filter((lot) => lot.is_active) ?? [], [selectedAirport]);

  const ownsSelection = parkingSelection.airportCode === airportCode && parkingSelection.initialParkingLotId === initialParkingLotId;
  const preferredLot = ownsSelection && scopeControls && parkingSelection.value !== null ? parkingSelection.value : initialParkingLotId;
  const parkingLotId = selectableLots.find((lot) => lot.id === preferredLot)?.id ?? selectableLots[0]?.id ?? null;
  const setParkingLotId = (value: number | null) => setParkingSelection({ airportCode, initialParkingLotId, value });
  const { result, error, pending, handleSubmit } = useFeeQuote({ airportCode, parkingLotId, vehicleSize, entryAt, exitAt, onCalculate });


  return { timeForm, handleSubmit, airportCode, setAirportCode, parkingLotId, setParkingLotId, selectableLots, vehicleSize, setVehicleSize, pending, error, result };
}


function FeeAirportSelect({ airportCode, setAirportCode, onAirportChange, airports }: Pick<ReturnType<typeof useFeeCalculatorSelection>, "airportCode" | "setAirportCode"> & Pick<NonNullable<Parameters<typeof FeeCalculator>[0]>, "onAirportChange" | "airports">) {
  return (<label className="field">
          <span>공항</span>
          <select className="input" value={airportCode} onChange={(event) => { setAirportCode(event.target.value); onAirportChange?.(event.target.value); }}>
            {airports.map((airport) => (
              <option key={airport.code} value={airport.code}>
                {airport.name_ko}
              </option>
            ))}
          </select>
        </label>);
}


function FeeParkingSelect({ parkingLotId, setParkingLotId, onParkingLotChange, selectableLots }: Pick<ReturnType<typeof useFeeCalculatorSelection>, "parkingLotId" | "setParkingLotId" | "selectableLots"> & Pick<NonNullable<Parameters<typeof FeeCalculator>[0]>, "onParkingLotChange">) {
  return (<label className="field">
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
        </label>);
}
