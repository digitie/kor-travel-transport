"use client";

import { Activity, Bus, ChartNoAxesCombined, Database, Fuel, Home, LogOut, Map, Menu, Plane, Route, ShipWheel, TrainFront, Waypoints } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useId, useState, type ReactNode } from "react";
import { AppMenu } from "@kor-travel/ui";
import { InfoButton } from "./info-button";

// Map과 같은 비링크 그룹 제목 + 작업 페이지 구조다.
const groups = [
  { id: "overview", label: undefined, items: [["/", "홈", Home], ["/map", "교통 지도", Map]] },
  { id: "highways", label: "고속도로", items: [["/highways", "고속도로 지도", Route], ["/highways/statistics", "고속도로 통계", ChartNoAxesCombined]] },
  { id: "fuel", label: "유가", items: [["/fuel", "유가 지도", Fuel], ["/fuel/statistics", "유가 통계", ChartNoAxesCombined]] },
  { id: "trains", label: "기차", items: [["/rail", "철도", TrainFront], ["/rail/metro", "도시철도", TrainFront], ["/rail/mapping", "역 코드 매핑", Waypoints]] },
  { id: "buses", label: "버스", items: [["/bus/express", "고속버스", Bus], ["/bus/intercity", "시외버스", Bus]] },
  { id: "air-sea", label: "항공·여객선", items: [["/flights", "비행·공항", Plane], ["/ferry", "배편", ShipWheel]] },
  { id: "operations", label: "운영 관리", items: [["/collections", "수집 상태", Activity], ["/admin/dagster", "Dagster", Database], ["/api-test", "API 점검", ChartNoAxesCombined]] },
] as const;
const hrefs = groups.flatMap((group) => group.items.map(([href]) => String(href)));

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const navigationId = useId();
  const [menuOpen, setMenuOpen] = useState(false);
  function clearDashboardCache() { try { window.sessionStorage.removeItem("kor-travel-transport-dashboard-v1"); window.sessionStorage.removeItem("kor-travel-transport-dashboard-v2"); } catch { /* optional browser storage */ } }
  // 로그아웃 요청 중 이전 페이지의 늦은 응답이 캐시를 다시 쓸 수 있다.
  // 로그인 문서가 열린 뒤에도 정리해 이전 문서의 비동기 작업과 경합하지 않는다.
  useEffect(() => { if (pathname === "/login") clearDashboardCache(); }, [pathname]);
  if (pathname === "/login") return <>{children}</>;
  const activeHref = hrefs.filter((href) => href === "/" ? pathname === "/" : pathname === href || pathname.startsWith(`${href}/`)).sort((a, b) => b.length - a.length)[0];
  return (
    <div className="transport-shell">
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
            </div>
            <button type="button" className="mobile-menu-button" aria-label="주요 메뉴 열기" aria-controls={navigationId} aria-expanded={menuOpen} onClick={() => setMenuOpen((value) => !value)}><Menu aria-hidden="true" size={18} />메뉴</button>
            <div id={navigationId} className={`rail-nav common-menu${menuOpen ? " is-open" : ""}`} onClick={(event) => { if (event.target instanceof Element && event.target.closest("a")) setMenuOpen(false); }}>
              <AppMenu label="주요 메뉴" pathname={pathname} activeItemId={activeHref} linkComponent={Link}
                groups={groups.map((group) => ({ id: group.id, label: group.label, items: group.items.map(([href, label, Icon]) => ({ id: href, href, label, exact: href === "/", icon: <Icon aria-hidden="true" size={16} strokeWidth={1.8} /> })) }))} />
            </div>
            <form className="rail-footer" action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}>
              <button className="nav-link logout-button" type="submit"><LogOut aria-hidden="true" size={16} strokeWidth={1.8} /><span>로그아웃</span></button>
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
