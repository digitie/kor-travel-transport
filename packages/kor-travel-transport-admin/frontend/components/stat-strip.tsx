// SPDX-License-Identifier: GPL-3.0-or-later
// SPDX-FileCopyrightText: 2026 Youn-sok Choi (digitie)
// Origin: kor-travel-map@974e2d025 packages/kor-travel-map-admin/frontend/src/components/stat-strip.tsx
// Modified: 2026-10-24 — Transport 운영 홈의 공용 토큰과 기존 Card에 연결
import * as React from "react";
import Link from "next/link";

import { cn } from "@/lib/utils";

type StatusTone = "success" | "warning" | "destructive" | "info" | "neutral";
function formatCount(value: number | null, { loading = false } = {}) {
  return loading || value === null || !Number.isFinite(value) ? "—" : value.toLocaleString("ko-KR");
}

type StatStripItem = {
  /** React key(생략 시 label). */
  key?: string;
  /** 무엇의 수인가 — 짧은 명사(`활성 Feature`, `열린 이슈`). */
  label: string;
  /** 숫자면 ko-KR 천 단위로, null/undefined면 `—`. ReactNode(예: `1.2 GB`)도 허용. */
  value: React.ReactNode | number | null | undefined;
  /** 값 뒤 단위(`건`, `%`) — 값보다 작은 활자. **값이 없으면(`—`) 단위도 함께 사라진다.** */
  unit?: string;
  /** 값 아래 한 줄(변화량·마지막 갱신·상태 문구). StatusBadge를 넣어도 된다. */
  caption?: React.ReactNode;
  /** 라벨 앞 상태 dot의 톤(선택). 값 자체는 항상 잉크색. */
  tone?: StatusTone;
  /** 라벨을 링크로(해당 목록 페이지). */
  href?: string;
  /** 이 항목만 로딩 중 — 값 자리에 `—`. */
  loading?: boolean;
  /** e2e 훅. */
  testId?: string;
};

type StatStripProps = {
  items: StatStripItem[];
  /** 전체 로딩 — 모든 값이 `—`(가짜 0 금지, M36). */
  isLoading?: boolean;
  /** 값 크기: `lg`는 대시보드 stat(30px), `default`는 패널 요약(20px). */
  size?: "default" | "lg";
  /** 컨테이너 없는 영역에서만 hairline 프레임을 켠다. */
  framed?: boolean;
  ariaLabel?: string;
  className?: string;
};

const TONE_DOT: Record<StatusTone, string> = {
  success: "bg-kt-success",
  warning: "bg-kt-warning",
  destructive: "bg-kt-destructive",
  info: "bg-kt-info",
  neutral: "bg-kt-text-tertiary",
};

function renderValue(value: StatStripItem["value"], loading: boolean): React.ReactNode {
  if (loading) return formatCount(null, { loading: true });
  if (value === null || value === undefined) return formatCount(null);
  if (typeof value === "number") return formatCount(value);
  return value;
}

/**
 * 값이 실제로 있는가. 없으면(로딩 중이든, 응답이 null이든) **단위를 함께 감춘다** —
 * `— 개`/`— 건`은 "0개"만큼이나 없는 값을 있는 것처럼 읽히게 만든다(M36 가짜 값 금지).
 * 단위는 값의 일부지 라벨의 일부가 아니다.
 */
function hasValue(value: StatStripItem["value"], loading: boolean): boolean {
  return !loading && value !== null && value !== undefined;
}

/**
 * 타이포그래피 stat strip(design.md §Macrostructure dashboard · M25/M37) — 아이콘 타일·카드 그리드
 * 없이 숫자 + 라벨을 hairline으로만 구분한다. KPI 표기의 유일한 idiom: 홈·ops 요약이 모두 이걸 쓴다.
 */
function StatStrip({
  items,
  isLoading = false,
  size = "default",
  framed = false,
  ariaLabel,
  className,
}: StatStripProps) {
  return (
    <dl
      aria-busy={isLoading || undefined}
      aria-label={ariaLabel}
      className={cn(
        "grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-y-4 [&>*:not(:first-child)]:border-l [&>*:not(:first-child)]:border-kt-border",
        framed && "rounded-kt-panel border border-kt-border bg-kt-surface-card px-2 py-4",
        className,
      )}
      data-slot="stat-strip"
    >
      {items.map((item) => {
        const loading = isLoading || item.loading === true;
        const labelNode = item.href ? (
          <Link
            className="rounded-kt-control underline-offset-4 hover:text-kt-text-primary hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-kt-focus"
            href={item.href}
          >
            {item.label}
          </Link>
        ) : (
          item.label
        );
        return (
          <div
            className="flex min-w-0 flex-col gap-1 px-4 first:pl-0"
            data-testid={item.testId}
            key={item.key ?? item.label}
          >
            <dt className="flex items-center gap-1.5 text-kt-xs font-medium text-kt-text-secondary">
              {item.tone ? (
                <span
                  aria-hidden="true"
                  className={cn("size-1.5 shrink-0 rounded-full", TONE_DOT[item.tone])}
                />
              ) : null}
              <span className="truncate">{labelNode}</span>
            </dt>
            <dd className="flex min-w-0 flex-col gap-1">
              <span
                aria-busy={loading || undefined}
                className={cn(
                  "flex items-baseline gap-1 font-semibold tabular-nums text-kt-text-primary",
                  size === "lg" ? "text-kt-2xl" : "text-kt-lg",
                  loading && "text-kt-text-tertiary",
                )}
              >
                <span className="truncate">{renderValue(item.value, loading)}</span>
                {item.unit && hasValue(item.value, loading) ? (
                  <span className="text-kt-xs font-medium text-kt-text-secondary">{item.unit}</span>
                ) : null}
              </span>
              {item.caption ? (
                <span className="text-kt-2xs text-kt-text-secondary">{item.caption}</span>
              ) : null}
            </dd>
          </div>
        );
      })}
    </dl>
  );
}

export { StatStrip };
export type { StatStripItem, StatStripProps };
