"use client";

import { AdminShell as CommonAdminShell } from "@kor-travel/ui/admin-shell";
import { AppMenu, type AppMenuLinkProps } from "@kor-travel/ui/app-menu";
import { LogOutIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { NAV_GROUPS, getActiveAdminItem } from "@/components/admin-nav";
import { cn } from "@/lib/utils";

export { PageHeader } from "@/components/page-header";
export type { PageHeaderProps, AdminBreadcrumb } from "@/components/page-header";

// 공통 메뉴가 compact 상태의 접근성 이름·툴팁을 전달한다. Next Link는 이를 보존한다.
function AdminMenuLink(props: AppMenuLinkProps) {
  return <Link {...props} />;
}

const COMMON_MENU_GROUPS = NAV_GROUPS.map((group) => ({
  id: group.group ?? "root",
  label: group.group ?? undefined,
  items: group.items.map(({ href, label, icon: Icon }) => ({
    id: href,
    href,
    label,
    icon: <Icon aria-hidden="true" className="size-4" />,
  })),
}));

const SIDEBAR_COLLAPSED_KEY = "kor-travel-transport:sidebar-collapsed";
const DASHBOARD_CACHE_KEYS = ["kor-travel-transport-dashboard-v1", "kor-travel-transport-dashboard-v2"] as const;

function clearDashboardCache() {
  try {
    for (const key of DASHBOARD_CACHE_KEYS) window.sessionStorage.removeItem(key);
  } catch {
    // 선택 저장소가 막혀도 로그아웃과 화면 이동은 계속한다.
  }
}

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const active = getActiveAdminItem(pathname);

  // 이전 문서의 늦은 응답이 캐시를 다시 쓴 경우 로그인 문서에서도 정리한다.
  useEffect(() => {
    if (pathname === "/login") clearDashboardCache();
  }, [pathname]);

  if (pathname === "/login") return <>{children}</>;

  return (
    <CommonAdminShell
      area="교통"
      title={active?.label ?? "관리"}
      navigationKey={pathname}
      collapsedStorageKey={SIDEBAR_COLLAPSED_KEY}
      labels={{ collapseRail: "좌측 메뉴 접기", expandRail: "좌측 메뉴 펼치기" }}
      testId="admin-shell"
      mainId="main-content"
      mainClassName="px-6 py-6"
      menu={(
        <AppMenu
          groups={COMMON_MENU_GROUPS}
          activeItemId={active?.href ?? null}
          pathname={pathname}
          label="주요 메뉴"
          linkComponent={AdminMenuLink}
          testId="transport-common-menu"
        />
      )}
      brand={({ collapsed }) => (
        <Link
          href="/"
          aria-label="kor-travel-transport admin"
          className="flex min-w-0 items-baseline gap-1.5 rounded-control text-text-primary no-underline hover:no-underline"
        >
          <span className="truncate text-sm font-semibold tracking-tight">
            {collapsed ? "ktt" : "kor-travel-transport"}
          </span>
          {!collapsed ? <span className="text-2xs font-medium text-text-tertiary">admin</span> : null}
        </Link>
      )}
      railFooter={({ collapsed }) => <ButtonLogout collapsed={collapsed} />}
    >
      {children}
    </CommonAdminShell>
  );
}

function ButtonLogout({ collapsed = false }: { collapsed?: boolean }) {
  // 스크립트가 없어도 POST/303으로 로그아웃하며 이전 문서의 대시보드 캐시를 지운다.
  return (
    <form action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}>
      <button
        aria-label={collapsed ? "로그아웃" : undefined}
        className={cn(
          "relative flex h-control-sm w-full items-center gap-2.5 rounded-control px-3 text-xs font-medium whitespace-nowrap text-text-secondary hover:bg-surface-subtle hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
          collapsed && "justify-center gap-0 px-0",
        )}
        title={collapsed ? "로그아웃" : undefined}
        type="submit"
      >
        <LogOutIcon aria-hidden="true" className="size-4 shrink-0 text-icon-default" />
        <span className={cn(collapsed && "sr-only")}>로그아웃</span>
      </button>
    </form>
  );
}
