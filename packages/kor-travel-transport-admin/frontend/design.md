# Transport 관리 화면 디자인

## 기준과 범위

기준은 `kor-travel-map` admin 프론트엔드의 최신 `origin/main`(a9adb16e2)이다.
레이아웃·내비게이션·로그인·공용 컴포넌트·토큰 이름·간격·형태·모션·포커스 규칙은 map과 같다.
kor-travel-geo와 kor-travel-weather 화면은 기준이 아니다.

색 값만 다르다. 색은 `app/transport-palette.css`가 정본이며 Transport의 기존 값
(표면·문자·파랑 brand·상태색)을 쓴다. 새 색은 더하지 않는다.

의도한 편차는 네 가지다.

1. 색 파생: Transport 팔레트에 없는 토큰은 기존 값에서 가져온다. `info`는 brand,
   `text-disabled`는 control-line, `chart-2..5`는 텍스트 단계, `compare-b`는 text-secondary,
   `overlay`·`shadow-modal`은 text-primary 색조에 map의 alpha·고도만 옮긴다.
2. 서체: Geist Mono는 `next/font/google`로 받지 않는다. 빌드가 네트워크를 요구하지 않도록
   Pretendard 스택(`@kor-travel/tokens/font.css`)만 쓰고 mono는 시스템 monospace로 떨어진다.
3. 페이지 헤더: map은 AdminShell이 헤더를 그리지만 Transport는 루트 레이아웃이 셸을 감싸고
   페이지가 `PageHeader`를 호출한다. 마크업·클래스는 map과 같고 `main` 안에 그려진다.
   `description`은 예전 InfoButton처럼 HelpTip으로 연다.
4. 메뉴·브랜드: 그룹·라우트·라벨·아이콘은 Transport의 기존 메뉴를 그대로 쓴다.
   워드마크는 `kor-travel-transport admin`, 접힘 축약형은 `ktt`, 접힘 저장 키는
   `kor-travel-transport:sidebar-collapsed`다.

남은 전환 상태: `app/globals.css`의 `legacy` 레이어에 Transport 전용 클래스가 남아 있다.
도메인 화면 전환이 끝나면 쓰지 않는 규칙을 지운다.

교통 이용자가 장소와 운항을 비교하는 실용적인 화면이며 운영 상태는 별도 메뉴로 분리한다.
기존 parking-radar의 화면과 스타일은 변경하지 않는다.

## 공통 구조

- 셸은 map과 같다. lg 이상에서 17rem 사이드 레일이 고정되고, 접힘 상태는 저장되며, 로그아웃은 레일 하단에 있다.
  lg 미만에서는 로그아웃이 아이콘 버튼으로 보이며 숨기지 않는다. 로그아웃은 POST `/api/auth/logout` 후 `/login`으로 이동한다.
- 검색·필터 → 지도/목록 전환 → 선택 항목 상세 순서다. 상세는 지도·목록 옆에 분리된 aside로 둔다.
- 모바일에서는 상세를 검색 바로 아래에 두고 목록보다 먼저 읽게 한다. 닫으면 장소 선택으로 포커스를 돌린다.
- 간격·형태·포커스·모션은 map의 토큰과 규칙을 따른다. 장식 모션은 없고 reduced-motion을 따른다.
- 입력·버튼 높이는 map의 `--control-h`(36px)와 `--control-h-sm`(30px)을 쓰고, 터치 환경에서는 최소 44px을 지킨다.
- 의미 없는 장식·진입 애니메이션·가짜 통계는 사용하지 않는다.
- 가격에는 유종·단위·관측 시각을, 시간표에는 출발/도착·운항일·배/등급·요금을 붙인다.
- 좌표 없음, 시간표 미수집, 수집 완료지만 운항 없음은 각각 다른 상태다.
- 지도는 zoom 11 미만에서 묶음을 유지한다. 이후에도 현재 화면 안 장소 수가
  화면 면적/22,000px²(최소 6·최대 60곳)를 넘으면 반경 110px 묶음을 유지한다.
  유종을 하나로 좁히면 반경은 80px다. 드문 장소도 반경 60px 내 겹침은 묶는다.
  선택한 장소는 묶음 밖에 표시해 상세와 연결한다.
  VWorld Base의 최대 확대 19를 넘겨야 분리되는 묶음은 장소 선택 목록으로 열어
  같은 좌표에 있는 역·항구도 개별 상세를 확인할 수 있게 한다.
- 검색과 선택만으로 외부 provider를 호출하지 않는다. 저장 데이터 조회와 명시적 보충을 분리한다.

## 토큰·상태

- 토큰 이름과 구조는 `@kor-travel/tokens` 0.1.1(`theme.css`, `radix.css`, `font.css`)을 따른다.
  `app/globals.css`가 이를 import하고, `app/transport-palette.css`가 색 값만 Transport 팔레트로 덮는다.
- 공용 CSS는 `@kor-travel/ui` 0.2.0의 `dagster.css`와 `map-controls.css`를 map과 같이 쓴다.
- 공용 UI 컴포넌트는 `components/ui/`(map 기준 복제본)와 `@kor-travel/ui`를 쓴다. 새 컴포넌트는 map에 대응물이 없을 때만 만든다.
- 포커스 표시, 선택 상태, 로딩, 빈 결과, 오류, 재시도, disabled 설명을 제공한다.
- 320/375/414/768px와 데스크톱에서 검증한다. 장식 모션은 없으며 reduced-motion을 따른다.
- 차트는 Apache ECharts를 유지한다.
- 버전: `@kor-travel/ui` 0.2.0, `@kor-travel/tokens` 0.1.1로 map과 같다. 고정 정보는 `vendor/README.md`에 있다.

## 실제 화면 검증

2026-09-28 후속: 분리된 우측 패널에서 제목·기준정보 시각·출도착·장소 정보를 구분한다.
모바일에서는 상세를 위에 배치하고 닫으면 장소 선택으로 포커스를 돌린다.
Dagster는 요약 카드·최근 실행 표·펼치는 스케줄 표를 사용한다. 교통별 장시간 기준(job별 실행 상한)을 쓰고
기준이 없을 때만 10분을 적용한다. KST 표시는 유지한다. 이 변경의 운영 검증은 진행 중이다.

Hallmark의 정보 위계·빈 상태 구분·키보드 포커스·반응형 기준을 적용했다.
2026-09-27 n150에서 실제 유가 마커, 소청도 운항 카드, 공항 저장 주차 현황,
고속도로 돌발·소통, 16개 수집 영역을 확인했다. 긴 장소명의 select가 상세 패널을
밀어내는 문제는 실제 화면에서 발견해 최소 폭과 줄바꿈으로 고쳤다. 가격을
overflow로 숨기지 않고 패널 자체의 가로 넘침을 1440/375px에서 검사한다.

사용자가 map 최신 UI 복제를 요청했으므로 새 브랜드·레이아웃 변주는 적용하지 않는다.
