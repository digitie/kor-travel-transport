"use client";
// Hallmark · genre: editorial-utilitarian · macrostructure: Rail-Workbench · design-system: design.md · designed-as-app

import { LogOutIcon, PanelLeftCloseIcon, PanelLeftOpenIcon } from "lucide-react";
import Link from "next/link";
import { AppMenu, type AppMenuLinkProps } from "@kor-travel/ui/app-menu";
import { usePathname } from "next/navigation";
import { createContext, useContext, useEffect, useRef, useSyncExternalStore, type ReactNode } from "react";

import { NAV_GROUPS, getActiveAdminItem } from "@/components/admin-nav";
import { buttonVariants } from "@/components/ui/button-variants";
import { cn } from "@/lib/utils";

// 기존 `@/components/admin-shell` 호출부가 PageHeader를 그대로 가져가도록 재수출한다.
export { PageHeader } from "@/components/page-header";
export type { PageHeaderProps, AdminBreadcrumb } from "@/components/page-header";

// 레일을 접으면 라벨 span이 숨으므로 링크에 이름과 툴팁을 직접 준다.
const SidebarCollapsedContext = createContext(false);
const LABEL_BY_HREF = new Map<string, string>(NAV_GROUPS.flatMap((group) => group.items.map((item) => [item.href, item.label] as const)));

function AdminMenuLink(props: AppMenuLinkProps) {
  const collapsed = useContext(SidebarCollapsedContext);
  const label = collapsed ? LABEL_BY_HREF.get(props.href) : undefined;
  return <Link {...props} aria-label={label ?? props["aria-label"]} title={label ?? props.title} />;
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
const SIDEBAR_PREFERENCE_EVENT = "kor-travel-transport:sidebar-preference";
const MAIN_CONTENT_ID = "main-content";
/** 로그아웃 요청 중 이전 페이지의 늦은 응답이 다시 쓰는 대시보드 캐시 키. */
const DASHBOARD_CACHE_KEYS = ["kor-travel-transport-dashboard-v1", "kor-travel-transport-dashboard-v2"] as const;

/**
 * Rail nav row / footer row 레시피 (design.md §Macrostructure N3 · M9).
 * flat row · 30px · 500 · hover surface-subtle · pressed surface-muted · focus = 단일 outline 레시피.
 */
const railRowClass =
  "relative flex h-control-sm shrink-0 items-center gap-2.5 rounded-control px-3 text-xs font-medium whitespace-nowrap text-text-secondary transition-[color,background-color] duration-fast ease-out hover:bg-surface-subtle hover:text-text-primary focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus active:bg-surface-muted";

const railRowCollapsedClass = "lg:size-control lg:justify-center lg:gap-0 lg:px-0";

function subscribeSidebar(listener: () => void) {
  window.addEventListener("storage", listener);
  window.addEventListener(SIDEBAR_PREFERENCE_EVENT, listener);
  return () => {
    window.removeEventListener("storage", listener);
    window.removeEventListener(SIDEBAR_PREFERENCE_EVENT, listener);
  };
}
// 저장소 쓰기가 막힌 환경(사생활 보호 모드 등)에서는 이 탭의 선택을 메모리에 둔다.
let unsavedSidebar: boolean | null = null;
function readSidebar() {
  if (unsavedSidebar !== null) return unsavedSidebar;
  try {
    return window.localStorage.getItem(SIDEBAR_COLLAPSED_KEY) === "1";
  } catch {
    return false;
  }
}
const serverSidebar = () => false;

function clearDashboardCache() {
  try {
    for (const key of DASHBOARD_CACHE_KEYS) window.sessionStorage.removeItem(key);
  } catch {
    // 선택 저장소라 실패해도 화면 이동을 막지 않는다.
  }
}

export function AdminShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const menuContainerRef = useRef<HTMLDivElement | null>(null);
  const sidebarCollapsed = useSyncExternalStore(subscribeSidebar, readSidebar, serverSidebar);
  const activeHref = getActiveAdminItem(pathname)?.href;

  // 로그아웃 요청 중 이전 페이지의 늦은 응답이 캐시를 다시 쓸 수 있다.
  // 로그인 문서가 열린 뒤에도 정리해 이전 문서의 비동기 작업과 경합하지 않는다.
  useEffect(() => {
    if (pathname === "/login") clearDashboardCache();
  }, [pathname]);

  useEffect(() => {
    if (typeof window === "undefined" || window.innerWidth >= 1024) return;
    // reduced-motion이면 smooth scroll 대신 즉시 이동한다.
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    menuContainerRef.current?.querySelector("[aria-current=page]")?.scrollIntoView({
      behavior: reduceMotion ? "auto" : "smooth",
      block: "nearest",
      inline: "center",
    });
  }, [activeHref]);

  if (pathname === "/login") return <>{children}</>;

  const toggleSidebar = () => {
    try {
      window.localStorage.setItem(SIDEBAR_COLLAPSED_KEY, sidebarCollapsed ? "0" : "1");
      unsavedSidebar = null;
    } catch {
      // 저장하지 못해도 이번 화면의 접힘 상태는 메모리 값으로 반영한다.
      unsavedSidebar = !sidebarCollapsed;
    }
    window.dispatchEvent(new Event(SIDEBAR_PREFERENCE_EVENT));
  };

  return (
    <div className="min-h-dvh bg-surface-page text-text-primary" data-testid="admin-shell">
      {/* M11: skip link — rail의 모든 메뉴를 건너뛰어 <main>으로. nav 밖(링크 수 보존). */}
      <a
        className="sr-only focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50 focus:rounded-control focus:border focus:border-border focus:bg-card focus:px-3 focus:py-2 focus:text-xs focus:font-medium focus:text-text-primary focus:shadow-elevated focus:outline-2 focus:outline-offset-2 focus:outline-focus"
        href={`#${MAIN_CONTENT_ID}`}
      >
        본문으로 건너뛰기
      </a>
      <div
        className={cn(
          "grid min-h-dvh min-w-0",
          sidebarCollapsed ? "lg:grid-cols-[4rem_minmax(0,1fr)]" : "lg:grid-cols-[16rem_minmax(0,1fr)]",
        )}
      >
        {/* Rail (N3): card 위 hairline 분리, rest shadow 없음. lg 에서 sticky 전체 높이. */}
        <aside
          aria-label="관리자 사이드바"
          className="min-w-0 border-b border-border bg-card lg:sticky lg:top-0 lg:h-dvh lg:self-start lg:border-r lg:border-b-0"
          data-slot="admin-shell-rail"
        >
          <div className="flex h-full min-w-0 flex-col">
            <div
              className={cn(
                "flex h-14 shrink-0 items-center justify-between gap-2 border-b border-border px-4",
                sidebarCollapsed && "lg:h-auto lg:flex-col lg:justify-center lg:gap-1 lg:px-0 lg:py-2",
              )}
            >
              {/* 타이포 워드마크 — 아이콘 타일 없음(M9). 접힘 시 축약형 `ktt`. */}
              <Link
                aria-label="kor-travel-transport admin"
                className={cn(
                  "flex min-w-0 items-baseline gap-1.5 rounded-control text-text-primary no-underline hover:no-underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus",
                  sidebarCollapsed && "lg:justify-center",
                )}
                href="/"
              >
                <span className={cn("truncate text-sm font-semibold tracking-tight", sidebarCollapsed && "lg:hidden")}>
                  kor-travel-transport
                </span>
                <span className={cn("text-2xs font-medium text-text-tertiary", sidebarCollapsed && "lg:hidden")}>
                  admin
                </span>
                <span
                  aria-hidden="true"
                  className={cn("hidden text-xs font-semibold tracking-tight", sidebarCollapsed && "lg:inline")}
                >
                  ktt
                </span>
              </Link>
              <div className="flex shrink-0 items-center gap-1">
                <ButtonLogout className="lg:hidden" iconOnly />
                <button
                  aria-label={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                  className={cn(buttonVariants({ variant: "ghost", size: "icon-sm" }), "hidden lg:inline-flex")}
                  title={sidebarCollapsed ? "좌측 메뉴 펼치기" : "좌측 메뉴 접기"}
                  type="button"
                  onClick={toggleSidebar}
                >
                  {sidebarCollapsed ? <PanelLeftOpenIcon aria-hidden="true" /> : <PanelLeftCloseIcon aria-hidden="true" />}
                </button>
              </div>
            </div>
            <div
              ref={menuContainerRef}
              data-collapsed={sidebarCollapsed}
              className="map-common-menu map-common-surface min-h-0 max-w-full overflow-x-auto px-2 py-2 lg:flex-1 lg:overflow-x-hidden lg:overflow-y-auto"
            >
              <SidebarCollapsedContext value={sidebarCollapsed}>
              <AppMenu
                groups={COMMON_MENU_GROUPS}
                activeItemId={activeHref ?? null}
                pathname={pathname}
                label="주요 메뉴"
                linkComponent={AdminMenuLink}
                testId="transport-common-menu"
              />
              </SidebarCollapsedContext>
            </div>
            {/* 로그아웃 = rail footer의 plain row(M9). <lg 에서는 상단 워드마크 행의 아이콘 버튼이 대신한다. */}
            <div
              className={cn(
                "hidden shrink-0 border-t border-border p-2 lg:block",
                sidebarCollapsed && "lg:flex lg:justify-center",
              )}
            >
              <ButtonLogout collapsed={sidebarCollapsed} />
            </div>
          </div>
        </aside>
        <main
          className="min-w-0 flex-1 px-6 py-6 focus-visible:outline-0"
          data-slot="admin-shell-main"
          id={MAIN_CONTENT_ID}
          tabIndex={-1}
        >
          {children}
        </main>
      </div>
    </div>
  );
}

function ButtonLogout({
  collapsed = false,
  iconOnly = false,
  className,
}: {
  /** lg rail 접힘 — 라벨을 lg 에서만 숨긴다. */
  collapsed?: boolean;
  /** 모든 breakpoint 에서 아이콘만(<lg 상단 행). */
  iconOnly?: boolean;
  className?: string;
}) {
  const labelHidden = iconOnly || collapsed;
  // 일반 폼 POST다. 스크립트가 없거나 오류 화면에서도 동작하고, 서버의 303이 곧바로 /login 문서로 이동시킨다.
  // 제출 직전에 대시보드 캐시를 지워 이전 화면의 데이터가 다음 로그인에 남지 않게 한다.
  return (
    <form action="/api/auth/logout" method="post" onSubmit={clearDashboardCache}>
      <button
        aria-label={labelHidden ? "로그아웃" : undefined}
        className={cn(
          railRowClass,
          // 상단 행의 아이콘 버튼은 터치 환경에서 최소 44px 대상을 지킨다.
          iconOnly ? "size-control-sm justify-center gap-0 px-0 pointer-coarse:size-11" : "w-full",
          !iconOnly && collapsed && railRowCollapsedClass,
          className,
        )}
        title={labelHidden ? "로그아웃" : undefined}
        type="submit"
      >
        <LogOutIcon aria-hidden="true" className="size-4 shrink-0 text-icon-default" />
        <span className={cn(iconOnly ? "sr-only" : collapsed && "lg:hidden")}>로그아웃</span>
      </button>
    </form>
  );
}
