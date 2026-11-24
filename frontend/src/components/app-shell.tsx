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
import { useId, type ComponentType } from "react";
import { MapFilterBar, MapFilterField } from "@kor-travel/ui/map-controls";

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

// 상단 바·탭·버튼은 transport 관리자(@kor-travel/ui AdminShell 상단 바, TabsList line 변형)와 같은 모양이다.
const desktopTabClass = (active: boolean) =>
  `relative inline-flex shrink-0 items-center gap-1.5 px-2 text-sm font-medium transition-colors after:absolute after:inset-x-1 after:bottom-0 after:h-0.5 after:bg-foreground ${
    active ? "text-foreground after:opacity-100" : "text-muted-foreground after:opacity-0 hover:text-foreground"
  }`;

const tabbarLinkClass = (active: boolean) =>
  `flex min-h-14 flex-col items-center justify-center gap-1 px-1 text-2xs font-medium ${
    active ? "text-brand" : "text-muted-foreground"
  }`;

export function AppShell({ children }: { children: React.ReactNode }) {
  // pages API(`src/pages/api/full-history.ts`)가 있으면 usePathname 타입이 nullable이 된다. App Router 화면에서는 항상 값이 있다.
  const pathname = usePathname() ?? "/";
  const fieldId = useId();
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
    <div className="parking-radar parking-public flex min-h-dvh flex-col">
      <header className="border-b border-border bg-card">
        <div className="page-shell flex min-h-12 items-center gap-2">
          <h1 className="m-0 min-w-0 shrink truncate text-md font-semibold">공항 주차 현황</h1>

          {/* 데스크톱: 제목 옆 line 탭. 모바일에서는 하단 탭바가 대신하므로 숨긴다. */}
          <nav className="ml-4 hidden self-stretch lg:flex" aria-label="주요 메뉴">
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

          {/* 관리자 상단 바 actions와 같은 자리. 모바일은 아이콘만 남겨 한 줄을 지킨다. */}
          <Button
            aria-label="새로고침"
            className="public-refresh ml-auto"
            variant="outline"
            size="lg"
            type="button"
            onClick={onRefresh}
          >
            <RefreshCw data-icon="inline-start" aria-hidden="true" />
            <span className="hidden sm:inline">새로고침</span>
          </Button>
        </div>
      </header>

      {/* 관리자 /parking과 같은 공용 필터 바. 레이블은 모든 폭에서 보인다. */}
      <div className="page-shell">
        <MapFilterBar className="public-filter-bar" role="group" aria-label="조회 범위">
          <MapFilterField label="공항 선택" htmlFor={`${fieldId}-airport`}>
            <select
              id={`${fieldId}-airport`}
              value={selectedAirportCode}
              onChange={(event) => onAirportChange(event.target.value)}
            >
              {airports.map((airport) => (
                <option key={airport.code} value={airport.code}>
                  {airport.name_ko}
                </option>
              ))}
            </select>
          </MapFilterField>
          <MapFilterField label="세부 주차장" htmlFor={`${fieldId}-lot`} className="public-lot-field">
            <select
              id={`${fieldId}-lot`}
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
          </MapFilterField>
        </MapFilterBar>
      </div>

      <main className="flex-1 pb-20 lg:pb-0">{children}</main>

      {/* 모바일 하단 탭바 — 조회 화면 4개. 데스크톱(lg)에서는 상단 탭이 대신한다. */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 border-t border-border bg-card lg:hidden"
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
