"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { LogOutIcon } from "lucide-react";
import Link from "next/link";
import { AdminShell as CommonAdminShell } from "@kor-travel/ui/admin-shell";
import { AppMenu } from "@kor-travel/ui/app-menu";
import { usePathname } from "next/navigation";
import { useEffect, type ReactNode } from "react";

import { ADMIN_AREA, NAV_GROUPS, getActiveAdminItem } from "@/components/admin-nav";
import { cn } from "@/lib/utils";

// 기존 `@/components/admin-shell` 호출부가 PageHeader를 그대로 가져가도록 재수출한다.
export { PageHeader } from "@/components/page-header";
export type { PageHeaderProps } from "@/components/page-header";

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

/** 기존 사이드바와 같은 키다. 값 "1"/"0"은 공용 셸이 그대로 읽고 같은 형식으로 쓴다. */
const SIDEBAR_COLLAPSED_KEY = "kor-travel-transport:sidebar-collapsed";
const MAIN_CONTENT_ID = "main-content";
/** 로그아웃 요청 중 이전 페이지의 늦은 응답이 다시 쓰는 대시보드 캐시 키. */
const DASHBOARD_CACHE_KEYS = ["kor-travel-transport-dashboard-v1", "kor-travel-transport-dashboard-v2"] as const;
const SHELL_LABELS = { collapseRail: "좌측 메뉴 접기", expandRail: "좌측 메뉴 펼치기" };

function clearDashboardCache() {
  try {
    for (const key of DASHBOARD_CACHE_KEYS) window.sessionStorage.removeItem(key);
  } catch {
    // 선택 저장소라 실패해도 화면 이동을 막지 않는다.
  }
}

/**
 * 공용 관리자 셸(@kor-travel/ui AdminShell). lg 이상은 접을 수 있는 좌측 rail, 그 아래는 상단 바의
 * 메뉴 버튼으로 여는 좌측 drawer다. 맨 위 한 줄은 "교통 - 페이지" 제목과 작은 설명만 둔다.
 * 페이지는 PageHeader(=AdminPageTitle)로 제목·설명·동작을 덮어쓴다. 첫 서버 렌더는 메뉴 라벨을 쓴다.
 */
export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const active = getActiveAdminItem(pathname);

  // 로그아웃 요청 중 이전 페이지의 늦은 응답이 캐시를 다시 쓸 수 있다.
  // 로그인 문서가 열린 뒤에도 정리해 이전 문서의 비동기 작업과 경합하지 않는다.
  useEffect(() => {
    if (pathname === "/login") clearDashboardCache();
  }, [pathname]);

  if (pathname === "/login") return <>{children}</>;

  return (
    <CommonAdminShell
      area={ADMIN_AREA}
      title={active?.label}
      brand={ADMIN_AREA}
      navigationKey={pathname ?? undefined}
      collapsedStorageKey={SIDEBAR_COLLAPSED_KEY}
      mainId={MAIN_CONTENT_ID}
      labels={SHELL_LABELS}
      mainClassName="px-4 py-4 sm:px-6 sm:py-6"
      testId="admin-shell"
      railFooter={({ collapsed }) => <ButtonLogout iconOnly={collapsed} />}
      menu={
        <AppMenu
          groups={COMMON_MENU_GROUPS}
          activeItemId={active?.href ?? null}
          pathname={pathname ?? "/"}
          label="주요 메뉴"
          linkComponent={Link}
          testId="transport-common-menu"
        />
      }
    >
      {children}
    </CommonAdminShell>
  );
}

/**
 * rail·drawer 하단의 로그아웃. 일반 폼 POST라 스크립트가 없거나 오류 화면에서도 동작하고,
 * 서버의 303이 곧바로 /login 문서로 이동시킨다. 제출 직전에 대시보드 캐시를 지운다.
 * 테두리·포커스는 공용 메뉴 링크와 같은 단일 outline 레시피(전역 :focus-visible)만 쓴다.
 */
function ButtonLogout({ iconOnly = false }: { iconOnly?: boolean }) {
  return (
    <form action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}>
      <button
        aria-label={iconOnly ? "로그아웃" : undefined}
        className={cn(
          "flex min-h-11 w-full items-center gap-2 rounded-control border-0 bg-transparent px-3 text-sm font-medium text-text-secondary hover:bg-surface-subtle hover:text-text-primary active:bg-surface-muted",
          iconOnly && "justify-center px-0",
        )}
        title={iconOnly ? "로그아웃" : undefined}
        type="submit"
      >
        <LogOutIcon aria-hidden="true" className="size-4 shrink-0 text-icon-default" />
        <span className={cn(iconOnly && "sr-only")}>로그아웃</span>
      </button>
    </form>
  );
}
