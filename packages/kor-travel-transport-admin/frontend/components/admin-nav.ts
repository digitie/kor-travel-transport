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
  ParkingCircleIcon,
  PlaneIcon,
  RouteIcon,
  ShipWheelIcon,
  TrainFrontIcon,
  WaypointsIcon,
} from "lucide-react";

/** 관리자 셸 상단 바의 영역 이름. 제목은 "교통 - 페이지" 형식이다. */
export const ADMIN_AREA = "교통";

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
    group: "주차장",
    section: "주차장",
    items: [{ href: "/parking-lots", label: "일반 주차장", icon: ParkingCircleIcon }],
  },
  {
    group: "기차",
    section: "기차",
    items: [
      { href: "/rail", label: "철도", icon: TrainFrontIcon },
      { href: "/rail/metro", label: "도시철도", icon: TrainFrontIcon },
      { href: "/rail/timetable", label: "시간표 조회", icon: TrainFrontIcon },
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
      { href: "/parking", label: "공항 주차장", icon: ParkingCircleIcon },
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

/**
 * 메뉴 항목별 페이지 제목·설명 정본. 셸 상단 바의 첫 서버 렌더와 페이지의 PageHeader가 같은 값을 써서
 * hydration 뒤 제목·설명이 바뀌지 않는다. 키는 NAV_GROUPS의 href다.
 */
export const PAGE_HEADINGS = {
  "/": { title: "운영 홈", description: "운영 상태를 한 화면에서 확인합니다." },
  "/map": { title: "교통 지도", description: "철도역·항구·버스 터미널·공항·일반 주차장·휴게소·도로 돌발 위치를 확인합니다." },
  "/highways": { title: "고속도로", description: "ITS 도로별 속도 지도와 저장된 도로 돌발·통제, 운전 지표를 확인합니다." },
  "/highways/statistics": { title: "고속도로 통계", description: "노선별 최근 구간 속도와 저속 구간 분포를 비교합니다." },
  "/fuel": { title: "유가 지도", description: "주유소별 최신 가격과 유종 정보를 지도에서 확인합니다." },
  "/fuel/statistics": { title: "유가 통계", description: "수집 완료 시점의 지역·고속도로별 가격과 최근 30일 추이를 확인합니다." },
  "/parking-lots": { title: "일반 주차장", description: "전국주차장정보 표준데이터의 저장된 총면수·요금·운영시간을 확인합니다. 실시간 잔여면은 제공하지 않습니다." },
  "/rail": { title: "철도", description: "지도에서 역을 선택하고 예정 시간표와 요금을 확인합니다." },
  "/rail/metro": { title: "도시철도", description: "노선과 가까운 역을 찾고 역 위치·연락처·예정 시간표를 확인합니다." },
  "/rail/timetable": { title: "시간표 조회", description: "역과 운행 기준을 선택하고 예정 출발·도착, 첫차·막차를 확인하세요." },
  "/rail/mapping": { title: "지하철역 코드 매핑", description: "KRIC 역 코드와 저장된 역 기준정보를 대조하고, 미연결 항목을 수동으로 보정합니다." },
  "/bus/express": { title: "고속버스", description: "터미널을 검색해 출발·도착 예정 시각과 등급별 요금을 비교합니다." },
  "/bus/intercity": { title: "시외버스", description: "출발·도착 터미널을 검색하고 오늘의 운행편을 확인합니다." },
  "/flights": { title: "비행·공항", description: "공항 위치, 오늘의 출도착 예정과 저장된 주차 현황을 확인합니다." },
  "/parking": { title: "공항 주차장", description: "현재 잔여면, 관측 이력, 요일·공휴일·임계치 패턴과 공개 기준 주차요금을 확인합니다. 과거 패턴은 입차 가능성을 보장하는 예측값이 아닙니다." },
  "/ferry": { title: "배편", description: "항구를 여러 곳 선택해 오늘부터 10일간의 저장 운항편을 비교합니다. 항로·터미널 기준자료도 함께 찾아볼 수 있습니다." },
  "/collections": { title: "수집 상태", description: "모든 제공기관의 연결·수집 상태와 Dagster 실행 기록을 확인합니다. 활성 설정과 실제 수집 성공을 구분합니다." },
  "/admin/dagster": { title: "Dagster", description: "자동 수집 작업의 실행 기록과 스케줄을 확인합니다. 제공기관별 저장 범위는 수집 상태 메뉴에서 확인하세요." },
  "/api-test": { title: "API 점검", description: "이 화면은 저장 데이터 조회 경로만 테스트합니다. 수집·백업 API와 지도 상세의 별도 좌표 보정 경로는 여기에 노출하지 않습니다." },
} as const satisfies Record<(typeof NAV_GROUPS)[number]["items"][number]["href"], { title: string; description: string }>;

/** 현재 경로가 속한 메뉴 항목의 제목·설명(없으면 undefined). */
export function getAdminPageHeading(pathname: string | null | undefined): { title: string; description: string } | undefined {
  const item = getActiveAdminItem(pathname);
  return item ? PAGE_HEADINGS[item.href] : undefined;
}
