"use client";

import { Activity, ChartNoAxesCombined, Database, LogOut, Map, Route, ShipWheel, TrainFront } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

const items = [
  ["/", "현황", Activity],
  ["/map", "지도", Map],
  ["/transport", "교통·유가", Route],
  ["/rail", "열차·도시철도", TrainFront],
  ["/ferry", "배편", ShipWheel],
  ["/admin/dagster", "Dagster", Database],
  ["/api-test", "API 점검", ChartNoAxesCombined],
] as const;

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  function clearDashboardCache() { try { window.sessionStorage.removeItem("kor-travel-transport-dashboard-v1"); window.sessionStorage.removeItem("kor-travel-transport-dashboard-v2"); } catch { /* optional browser storage */ } }
  // 로그아웃 요청 중 이전 페이지의 늦은 응답이 캐시를 다시 쓸 수 있다.
  // 로그인 문서가 열린 뒤에도 정리해 이전 문서의 비동기 작업과 경합하지 않는다.
  useEffect(() => { if (pathname === "/login") clearDashboardCache(); }, [pathname]);
  if (pathname === "/login") return <>{children}</>;
  return <div className="admin-layout"><aside className="rail"><Link className="brand" href="/"><strong>Kor Travel Transport</strong><span>운영 관리 화면</span></Link><nav className="nav"><p className="nav-label">운영</p>{items.map(([href, label, Icon]) => <Link className={pathname === href ? "active" : ""} href={href} key={href}><Icon aria-hidden="true" size={16} /> {label}</Link>)}</nav><form action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}><button className="sign-out" type="submit"><LogOut aria-hidden="true" size={15} /> 로그아웃</button></form></aside><main className="main">{children}</main></div>;
}

export function PageHeader({ title, description }: { title: string; description: string }) {
  return <header className="page-header"><p className="eyebrow">Kor Travel Transport</p><h1>{title}</h1><p>{description}</p></header>;
}
