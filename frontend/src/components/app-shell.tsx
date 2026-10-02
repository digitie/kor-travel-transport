"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Calculator,
  History,
  LayoutDashboard,
  RefreshCw,
} from "lucide-react";
import type { ComponentType } from "react";

import { Button } from "@/components/ui/button";
import { useDashboard } from "@/lib/dashboard-context";

type NavItem = {
  href: string;
  label: string;
  icon: ComponentType<{ className?: string }>;
};

const NAV_ITEMS: NavItem[] = [
  { href: "/", label: "현황", icon: LayoutDashboard },
  { href: "/analytics", label: "분석", icon: BarChart3 },
  { href: "/history", label: "과거조회", icon: History },
  { href: "/fees", label: "요금계산", icon: Calculator },
];

// 데스크톱/모바일 분기는 Tailwind 기본 lg(1024px) 브레이크포인트를 쓴다 - 이전 JS
// useViewportMode()의 860px 기준에서 의도적으로 올렸다(shadcn/Tailwind 표준값을 그대로
// 따름). 860~1023px 구간은 이전엔 데스크톱 레이아웃이었지만 지금은 모바일 레이아웃이다.

// 모바일 하단 탭바는 네 조회 화면을 그대로 둔다. 공개 앱에는 백업 등 관리 화면이 없다
// (2026-10-02 공개 백업 노출 사고, ADR-012).

function isActivePath(pathname: string, href: string): boolean {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

const desktopTabClass = (active: boolean) =>
  `inline-flex min-h-11 shrink-0 items-center gap-1.5 rounded-sm border-b-2 px-3 text-sm font-semibold transition-colors ${
    active
      ? "border-foreground text-foreground"
      : "border-transparent text-muted-foreground hover:border-border hover:text-foreground"
  }`;

const tabbarLinkClass = (active: boolean) =>
  `flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-xs font-semibold ${
    active ? "text-foreground" : "text-muted-foreground"
  }`;

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const {
    airports,
    selectedAirportCode,
    selectedParkingLotId,
    selectedAirportLots,
    onAirportChange,
    onParkingLotChange,
    onRefresh,
  } = useDashboard();

  return (
    <div className="flex min-h-dvh flex-col">
      <header className="border-b border-border bg-background">
        <div className="page-shell">
          <div className="page-header">
            <h1>공항 주차 현황</h1>
          </div>

          <div className="control-band">
            <label className="field">
              {/* 데스크톱은 레이블을 보여주고, 모바일은 한 줄(선택 2개 + 버튼) 폭을
                  확보하려고 sr-only로 시각적으로만 숨긴다 - select 자체의 aria-label로
                  접근성은 그대로 유지된다. */}
              <span className="sr-only lg:not-sr-only">공항 선택</span>
              <select
                aria-label="공항 선택"
                className="input"
                value={selectedAirportCode}
                onChange={(event) => onAirportChange(event.target.value)}
              >
                {airports.map((airport) => (
                  <option key={airport.code} value={airport.code}>
                    {airport.name_ko}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              <span className="sr-only lg:not-sr-only">세부 주차장</span>
              <select
                aria-label="세부 주차장"
                className="input"
                value={selectedParkingLotId ?? "all"}
                onChange={(event) =>
                  onParkingLotChange(event.target.value === "all" ? null : Number(event.target.value))
                }
              >
                <option value="all">전체 주차장</option>
                {selectedAirportLots.map((parkingLot) => (
                  <option key={parkingLot.id} value={parkingLot.id}>
                    {parkingLot.name}
                  </option>
                ))}
              </select>
            </label>
            {/* action-stack로 감싸지 않는다 - 그 클래스는 current-status-view.tsx의
                수동 수집 버튼+힌트(자식 2개) 쌍을 위한 860px 폭 이하 2열 그리드 규칙도
                갖고 있어서, 자식이 버튼 하나뿐인 여기서 재사용하면 빈 두 번째 칸이 실제
                폭을 차지해(381-1023px에서 측정: 44px가 아니라 98px) 모바일 한 줄
                레이아웃에서 select 두 개의 폭을 그만큼 빼앗는다(hostile review에서
                발견). 버튼을 control-band의 그리드 자식으로 직접 두면 `.button.secondary`
                자체의 `align-self: end`만으로 정렬이 충분하다. */}
            <Button
              aria-label="새로고침"
              className="button secondary refresh-button"
              variant="secondary"
              type="button"
              onClick={onRefresh}
            >
              <RefreshCw className="size-4" aria-hidden="true" />
              <span className="hidden lg:inline">새로고침</span>
            </Button>
          </div>

          {/* 데스크톱: 상단 탭 전부 인라인 노출. 모바일에서는 하단 탭바가 대신하므로 숨긴다. */}
          <nav className="hidden gap-1 pb-3 lg:flex" aria-label="주요 메뉴">
            {NAV_ITEMS.map((item) => {
              const active = isActivePath(pathname, item.href);
              const Icon = item.icon;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={desktopTabClass(active)}
                >
                  <Icon className="size-4" aria-hidden="true" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      </header>

      <main className="flex-1 pb-20 lg:pb-0">{children}</main>

      {/* 모바일 하단 탭바 — 조회 화면 4개. 데스크톱(lg)에서는 상단 탭이 대신한다. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-background lg:hidden"
        aria-label="하단 메뉴"
      >
        <ul className="m-0 grid list-none grid-cols-4 p-0 pb-[env(safe-area-inset-bottom)]">
          {NAV_ITEMS.map((item) => {
            const active = isActivePath(pathname, item.href);
            const Icon = item.icon;
            return (
              <li key={item.href}>
                <Link href={item.href} aria-current={active ? "page" : undefined} className={tabbarLinkClass(active)}>
                  <Icon className="size-5" aria-hidden="true" />
                  <span>{item.label}</span>
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </div>
  );
}
