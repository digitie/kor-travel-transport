"use client";

import { Activity, Bus, ChartNoAxesCombined, Database, Fuel, Home, LogOut, Map, PanelLeftClose, PanelLeftOpen, ParkingCircle, Plane, Route, ShipWheel, TrainFront, Waypoints } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createStore } from "zustand/vanilla";
import { useStore } from "zustand";
import { AppMenu, type AppMenuLinkProps } from "@kor-travel/ui";
import { Button } from "@kor-travel/ui/primitives";
import { InfoButton } from "./info-button";

const SidebarCollapsedContext = createContext(false);
function MenuLink(props: AppMenuLinkProps) {
  const collapsed = useContext(SidebarCollapsedContext);
  return <Link {...props} title={props.title ?? (collapsed ? props["aria-label"] : undefined)} />;
}
const sidebarStorageKey = "kor-travel-transport:sidebar-collapsed";

// Map과 같은 비링크 그룹 제목 + 작업 페이지 구조다.
const groups = [
  { id: "overview", label: undefined, items: [["/", "홈", Home], ["/map", "교통 지도", Map]] },
  { id: "highways", label: "고속도로", items: [["/highways", "고속도로 지도", Route], ["/highways/statistics", "고속도로 통계", ChartNoAxesCombined]] },
  { id: "fuel", label: "유가", items: [["/fuel", "유가 지도", Fuel], ["/fuel/statistics", "유가 통계", ChartNoAxesCombined]] },
  { id: "parking-lots", label: "주차장", items: [["/parking-lots", "일반 주차장", ParkingCircle]] },
  { id: "trains", label: "기차", items: [["/rail", "철도", TrainFront], ["/rail/metro", "도시철도", TrainFront], ["/rail/timetable", "시간표 조회", TrainFront], ["/rail/mapping", "역 코드 매핑", Waypoints]] },
  { id: "buses", label: "버스", items: [["/bus/express", "고속버스", Bus], ["/bus/intercity", "시외버스", Bus]] },
  { id: "air-sea", label: "항공·여객선", items: [["/flights", "비행·공항", Plane], ["/parking", "공항 주차장", ParkingCircle], ["/ferry", "배편", ShipWheel]] },
  { id: "operations", label: "운영 관리", items: [["/collections", "수집 상태", Activity], ["/admin/dagster", "Dagster", Database], ["/api-test", "API 점검", ChartNoAxesCombined]] },
] as const;
const hrefs = groups.flatMap((group) => group.items.map(([href]) => String(href)));
const mapPages = new Set(["/map", "/fuel", "/parking-lots", "/highways", "/rail", "/rail/metro", "/bus/express", "/bus/intercity", "/flights", "/ferry"]);

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const navigationRef = useRef<HTMLDivElement>(null);
  const [uiStore] = useState(() => createStore<{ sidebarCollapsed: boolean }>(() => ({ sidebarCollapsed: false })));
  const sidebarCollapsed = useStore(uiStore, (state) => state.sidebarCollapsed);
  useEffect(() => {
    try { if (window.localStorage.getItem(sidebarStorageKey) === "1") uiStore.setState({ sidebarCollapsed: true }); } catch { /* 저장소가 막혀도 메뉴는 사용할 수 있다. */ }
  }, [uiStore]);
  function toggleSidebar() {
    const collapsed = !uiStore.getState().sidebarCollapsed;
    uiStore.setState({ sidebarCollapsed: collapsed });
    try { window.localStorage.setItem(sidebarStorageKey, collapsed ? "1" : "0"); } catch { /* 선택 상태 저장은 선택 사항이다. */ }
  }
  useEffect(() => {
    const container = navigationRef.current;
    if (!container) return;
    let cancelled = false;
    let previousWidth = container.clientWidth;
    const keepActiveVisible = () => {
      if (cancelled || typeof window.matchMedia !== "function" || !window.matchMedia("(max-width: 1023px)").matches || !container.clientWidth) return;
      const active = container.querySelector<HTMLElement>('[data-slot="app-menu-link"][aria-current="page"]');
      if (!active) return;
      const menu = container.getBoundingClientRect();
      const item = active.getBoundingClientRect();
      const left = container.scrollLeft + item.left - menu.left - container.clientLeft - (container.clientWidth - item.width) / 2;
      const behavior = window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth";
      // 문서·입력 위치를 움직이지 않고 메뉴의 가로 스크롤만 조정한다.
      container.scrollTo?.({ left, top: container.scrollTop, behavior });
    };
    keepActiveVisible();
    const observer = typeof ResizeObserver === "function" ? new ResizeObserver(() => {
      const width = container.clientWidth;
      if (width === previousWidth) return;
      previousWidth = width;
      keepActiveVisible();
    }) : undefined;
    observer?.observe(container);
    const fonts = document.fonts;
    if (fonts) {
      void fonts.ready.then(keepActiveVisible);
      fonts.addEventListener("loadingdone", keepActiveVisible);
    }
    return () => {
      cancelled = true;
      observer?.disconnect();
      fonts?.removeEventListener("loadingdone", keepActiveVisible);
    };
  }, [pathname]);
  function clearDashboardCache() { try { window.sessionStorage.removeItem("kor-travel-transport-dashboard-v1"); window.sessionStorage.removeItem("kor-travel-transport-dashboard-v2"); } catch { /* optional browser storage */ } }
  // 로그아웃 요청 중 이전 페이지의 늦은 응답이 캐시를 다시 쓸 수 있다.
  // 로그인 문서가 열린 뒤에도 정리해 이전 문서의 비동기 작업과 경합하지 않는다.
  useEffect(() => { if (pathname === "/login") clearDashboardCache(); }, [pathname]);
  if (pathname === "/login") return <>{children}</>;
  const activeHref = hrefs.filter((href) => href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`)).sort((a, b) => b.length - a.length)[0];
  return (
    <div className="transport-shell" data-sidebar-collapsed={sidebarCollapsed} data-map-page={mapPages.has(pathname) || undefined} data-parking-page={pathname === "/parking" || undefined}>
      <a className="skip-link" href="#main-content">본문으로 건너뛰기</a>
      <div className="admin-layout" data-testid="admin-shell">
        <aside className="rail" aria-label="관리자 사이드바" data-slot="admin-shell-rail">
          <div className="rail-shell">
            <div className="rail-header">
              <Link className="brand" href="/" aria-label="Kor Travel Transport 홈">
                <span className="brand-mark"><Route aria-hidden="true" size={17} /></span>
                <span className="brand-wordmark">Transport</span>
                <span className="brand-subtitle">Admin UI</span>
              </Link>
              <Button variant="ghost" size="icon-sm" className="sidebar-collapse" type="button"
                aria-label={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                title={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"} onClick={toggleSidebar}>
                {sidebarCollapsed ? <PanelLeftOpen aria-hidden="true" size={16} /> : <PanelLeftClose aria-hidden="true" size={16} />}
              </Button>
            </div>
            <div ref={navigationRef} className="rail-nav common-menu">
              <SidebarCollapsedContext.Provider value={sidebarCollapsed}><AppMenu label="주요 메뉴" pathname={pathname} activeItemId={activeHref} linkComponent={MenuLink}
                groups={groups.map((group) => ({ id: group.id, label: group.label, items: group.items.map(([href, label, Icon]) => ({ id: href, href, label, exact: href === "/", icon: <Icon aria-hidden="true" size={16} strokeWidth={1.8} /> })) }))} /></SidebarCollapsedContext.Provider>
            </div>
            <form className="rail-footer" action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}>
              <Button variant="ghost" className="nav-link logout-button" aria-label="로그아웃" title={sidebarCollapsed ? "로그아웃" : undefined} type="submit"><LogOut aria-hidden="true" size={16} strokeWidth={1.8} /><span>로그아웃</span></Button>
            </form>
          </div>
        </aside>
        <main className="main" id="main-content" tabIndex={-1}><div className="page-body">{children}</div></main>
      </div>
    </div>
  );
}

export function PageHeader({ title, description, actions }: { title: string; description: string; actions?: ReactNode }) {
  const pathname = usePathname();
  return (
    <header className="page-header-wrap" data-slot="admin-shell-header">
      <div className="page-header">
        <div className="page-header-copy">
          <div className="page-context"><span className="page-path">{pathname}</span></div>
          <div className="page-header-row">
            <div className="section-title-row"><h1>{title}</h1>{description ? <InfoButton label={title}>{description}</InfoButton> : null}</div>
            {actions ? <div className="page-header-actions">{actions}</div> : null}
          </div>
        </div>
      </div>
    </header>
  );
}
