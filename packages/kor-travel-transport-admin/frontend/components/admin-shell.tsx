"use client";

import { Activity, ChartNoAxesCombined, Database, Fuel, LogOut, Route } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

const items = [
  ["/", "현황", Activity],
  ["/transport", "교통 수집", Route],
  ["/fuel", "유가", Fuel],
  ["/admin/dagster", "Dagster", Database],
  ["/api-test", "API 점검", ChartNoAxesCombined],
] as const;

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  function clearDashboardCache() { try { window.sessionStorage.removeItem("kor-travel-transport-dashboard-v1"); } catch { /* optional browser storage */ } }
  if (pathname === "/login") return <>{children}</>;
  return <div className="admin-layout"><aside className="rail"><Link className="brand" href="/"><strong>Kor Travel Transport</strong><span>운영 관리 화면</span></Link><nav className="nav"><p className="nav-label">운영</p>{items.map(([href, label, Icon]) => <Link className={pathname === href ? "active" : ""} href={href} key={href}><Icon aria-hidden="true" size={16} /> {label}</Link>)}</nav><form action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}><button className="sign-out" type="submit"><LogOut aria-hidden="true" size={15} /> 로그아웃</button></form></aside><main className="main">{children}</main></div>;
}

export function PageHeader({ title, description }: { title: string; description: string }) {
  return <header className="page-header"><p className="eyebrow">Kor Travel Transport</p><h1>{title}</h1><p>{description}</p></header>;
}
