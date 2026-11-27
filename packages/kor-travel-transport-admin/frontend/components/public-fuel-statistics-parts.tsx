"use client";

import { useEffect, useId, useState, type ReactNode, type RefObject } from "react";
import { Button } from "./ui/button";
import type { StatisticsLoadError } from "@/lib/public-fuel-statistics";

/** 라디오 묶음(분절 버튼 모양). 방향키로 옮겨 다닌다(브라우저 기본 라디오 동작). */
export function Segmented({ legend, name, options, value, onChange, disabled = [], note }: { legend: string; name: string; options: [string, string][]; value: string; onChange: (value: string) => void; disabled?: string[]; note?: string }) {
  const id = useId();
  const blocked = new Set(disabled);
  return <fieldset className="public-fuel-segmented" aria-describedby={note ? `${id}-note` : undefined}>
    <legend>{legend}</legend>
    <div role="presentation">
      {options.map(([option, label]) => <label key={option} data-checked={option === value || undefined} data-disabled={blocked.has(option) || undefined}>
        <input type="radio" name={`${id}-${name}`} value={option} checked={option === value} disabled={blocked.has(option)} onChange={() => onChange(option)} />
        <span>{label}</span>
      </label>)}
    </div>
    {note ? <p id={`${id}-note`} className="public-fuel-segmented-note">{note}</p> : null}
  </fieldset>;
}

/** 실패 안내와 다시 조회. 서버 Retry-After(최대 60초) 동안 남은 초를 보이고 막는다. 다시 조회하면 초점을 구역 제목으로 옮긴다. */
export function RetryAlert({ error, onRetry, what, focusTarget }: { error: StatisticsLoadError; onRetry: () => void; what: string; focusTarget: RefObject<HTMLElement | null> }) {
  const [retryIn, setRetryIn] = useState(error.retryAfter);
  useEffect(() => {
    if (retryIn <= 0) return;
    const timer = setTimeout(() => setRetryIn(value => Math.max(0, value - 1)), 1000);
    return () => clearTimeout(timer);
  }, [retryIn]);
  return <div className="public-fuel-stats-alert" role="alert">
    <p>{error.message}</p>
    <Button type="button" variant="outline" size="sm" disabled={retryIn > 0} onClick={() => { onRetry(); focusTarget.current?.focus(); }}>
      {what} 다시 조회{retryIn > 0 ? ` (${retryIn}초 후)` : ""}
    </Button>
  </div>;
}

/** 조회 중 표시. 화면 읽기 프로그램에는 조건마다 두 번씩 읽히지 않게 알리지 않는다(구역의 aria-busy와 결과 알림이 대신한다). */
export function Pending({ retrying, children }: { retrying: boolean; children: ReactNode }) {
  return <p className="public-fuel-stats-pending">{retrying ? "조회가 몰려 잠시 뒤 다시 조회하는 중…" : children}</p>;
}

