// 메뉴 정본. AdminShell(사이드바)과 PageHeader(섹션 라벨)가 같은 그룹·라우트를 쓴다.
// 이 파일에는 JSX가 없어 PageHeader와 AdminShell이 서로 순환 import하지 않는다.
import {
  ActivityIcon,
  BusIcon,
  ChartNoAxesCombinedIcon,
  DatabaseIcon,
  FuelIcon,
  HomeIcon,
  MapIcon,
  PlaneIcon,
  RouteIcon,
  ShipWheelIcon,
  TrainFrontIcon,
  WaypointsIcon,
} from "lucide-react";

/**
 * 작업 지향 nav 그룹 — nav·섹션 라벨·헤더 섹션 라벨의 단일 정본.
 * 그룹 헤더는 비링크이며 href는 존치하는 화면만 가리킨다. 라우트와 라벨은 Transport 기존 메뉴를 그대로 둔다.
 */
export const NAV_GROUPS = [
  {
    group: null,
    section: "개요",
    items: [
      { href: "/", label: "홈", icon: HomeIcon },
      { href: "/map", label: "교통 지도", icon: MapIcon },
    ],
  },
  {
    group: "고속도로",
    section: "고속도로",
    items: [
      { href: "/highways", label: "고속도로 지도", icon: RouteIcon },
      { href: "/highways/statistics", label: "고속도로 통계", icon: ChartNoAxesCombinedIcon },
    ],
  },
  {
    group: "유가",
    section: "유가",
    items: [
      { href: "/fuel", label: "유가 지도", icon: FuelIcon },
      { href: "/fuel/statistics", label: "유가 통계", icon: ChartNoAxesCombinedIcon },
    ],
  },
  {
    group: "기차",
    section: "기차",
    items: [
      { href: "/rail", label: "철도", icon: TrainFrontIcon },
      { href: "/rail/metro", label: "도시철도", icon: TrainFrontIcon },
      { href: "/rail/mapping", label: "역 코드 매핑", icon: WaypointsIcon },
    ],
  },
  {
    group: "버스",
    section: "버스",
    items: [
      { href: "/bus/express", label: "고속버스", icon: BusIcon },
      { href: "/bus/intercity", label: "시외버스", icon: BusIcon },
    ],
  },
  {
    group: "항공·여객선",
    section: "항공·여객선",
    items: [
      { href: "/flights", label: "비행·공항", icon: PlaneIcon },
      { href: "/ferry", label: "배편", icon: ShipWheelIcon },
    ],
  },
  {
    group: "운영 관리",
    section: "운영 관리",
    items: [
      { href: "/collections", label: "수집 상태", icon: ActivityIcon },
      { href: "/admin/dagster", label: "Dagster", icon: DatabaseIcon },
      { href: "/api-test", label: "API 점검", icon: ChartNoAxesCombinedIcon },
    ],
  },
] as const;

const navItems = NAV_GROUPS.flatMap((group) =>
  group.items.map((item) => ({ ...item, section: group.section })),
);

function isActive(pathname: string, href: string) {
  if (href === "/") {
    return pathname === "/";
  }
  return pathname === href || pathname.startsWith(`${href}/`);
}

/** 현재 경로가 속한 가장 긴 메뉴 항목(없으면 undefined). PageHeader의 섹션 라벨도 같은 규칙을 쓴다. */
export function getActiveAdminItem(pathname: string | null | undefined) {
  // 테스트처럼 라우터 밖에서 렌더하면 usePathname이 null을 준다.
  if (!pathname) return undefined;
  return navItems
    .filter((item) => isActive(pathname, item.href))
    .sort((a, b) => b.href.length - a.href.length)[0];
}
