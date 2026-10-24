# 이용 목적 중심 교통 관리자 개선 — 2026-10-24

## 구현과 소비 경계

`codex/transport-user-journeys`는 공통 지도 UI PR125 위의 후속이다. 운영 빌드·배포는 사용자 지시에 따라
통합 담당 에이전트가 수행한다. 이 작업은 운영 API·DB·수집기·Dagster 컨테이너를 교체하지 않았다.

- Map 운영 홈 배치를 재사용해 홈을 운영 요약·최근 실행·확인이 필요한 수집으로 바꿨다.
  고속도로·유가·기차·버스 메뉴를 묶고 `/transport`는 홈으로 이동한다.
- 고속도로 최근 15분 속도 분포 12지표, 유가 주유량·연비 기준 운영비 12지표를 제공한다.
  결측을 0으로 만들지 않으며 표본·산식은 제목 옆 정보 버튼에서 확인한다.
- 도시철도는 노선→역 검색, 내 근처 역, 넓은 지도, 작은 운영사·주소, 전화·편의시설·이후 출발을 제공한다.
  편의시설은 기존 저장 공개 XLSX 원문에 provider 파서를 적용하며 재수집을 요구하지 않는다.
- KRIC 역별 network/server 실패는 해당 요청을 저장하고 다음 역으로 진행한다. 연속 3회 실패 또는
  인증·quota·식별자 불일치는 중단한다. 시도 횟수에도 호출 간격·상한을 적용한다. 부분 실패는 Dagster 성공으로 숨기지 않는다.
- 일반철도 TAGO 15098552의 열차 종류·지역·역·실제 예정 시간표를 기존 `datagokr` SDK로 조회·저장한다.
  KTX/SRT/무궁화와 `0A` KTX-산천 코드를 보존한다. 접근 거부를 정상 빈 시간표로 처리하지 않는다.
- 코레일 공개 역 안내는 별도 `KorailPublicClient`가 파싱한다. KTX는 노선별, 일반철도는 권역별이다.
  양쪽 공개 자료에서 유일한 동일 역명만 좌표를 연결한다. 코레일과 TAGO 역 식별자를 추정 결합하지 않는다.
- 버스의 출발/도착 선택 시 해당 날짜에 **저장된 정상 시간표의 연결 후보**를 반대편에 표시한다.
  전체 터미널 검색과 실제 TAGO 시간표 조회를 유지한다. 전국 전체 연결을 확보한 기능은 아니다.
- 공항은 선택 즉시 현재 주차·이후 항공편을 조회하고 과거 같은 요일·시간대 주차 패턴을 제공한다.
  관측일별 평균을 같은 비중으로 계산하며 만차 관측일 비율을 입차 확률로 표현하지 않는다.

## 최신 UI 점검

- 제목 옆 `i` 버튼에 설명을 모아 PC·터치·키보드로 열고 Escape/닫기 버튼으로 닫는다.
  조회 실패·오래된 자료·예시 자료 경고는 화면에 남긴다.
- 모바일 메뉴는 접어서 상단 높이를 줄인다. 지도 높이는 기본 64dvh, 모바일 최소 22rem이며
  역 검색 결과 영역은 모바일 6rem까지만 차지한다. 버스 지도는 시간표보다 먼저 배치한다.
- 지도·시간표·주차 패턴 바로가기와 주소→지도 이동을 제공한다. 주유소 주소는 유가 지도를 해당 좌표로 연다.
  수집 작업명은 최근 해당 Dagster 실행을, 실행·스케줄은 외부 Dagster 상세를 연다.
- 공통 Map 필터·지도/목록 탭·실제 좌표/줌·지도 위 상세는 PR125/Common PR45의 구현을 계속 사용한다.

## API·저장

- `GET /v1/transport/rail/general/{catalog,stations,timetable,guide}`
- `GET /v1/transport/bus/connections`: `direction=departure|arrival`, `coverage=stored_routes`.
- `GET /v1/parking/outlook`: timezone 포함 `arrival_at`, 과거 7~60일, 기본 28일.
- `GET /v1/transport/highways/roads`, `/road-traffic?road_id=0010&direction=1`:
  키 없는 `python-krits-api@417e3d5`의 검증된 선택 도로 경로·속도를 직접 소비한다.
  도로 ID와 표시 노선번호는 구분하며 KREX 코드와 결합하지 않는다. 조회 시각은 원본 관측 시각이 아니다.
  worker별 catalog24시간·소통5분·캐시9개·하루96회 miss·공유1RPS·실패15분 보호를 둔다.
  catalog를 포함한 전체 조회25초, 응답5,000링크/100,000점 상한이며 실패를 정상 빈 응답으로 바꾸지 않는다.
  별도 DB·마이그레이션·전국 수집은 추가하지 않는다. 개발용 `ITS_CHROMIUM_EXECUTABLE_PATH`만 선택 설정이다.
- 미배포 migration0034는 `general_rail_query_snapshots`에 마지막 정상 응답만 저장한다.
  PK(operation,request_key), fetched_at index, operation CHECK, JSONB이며 32일 경과 캐시를 정리한다.
  기준정보·공개 안내 24시간, TAGO 시간표 15분 재사용; 실패 뒤 이전 저장본은 stale 표시다.
  TAGO와 키 없는 코레일 안내는 worker별 lock·보호 상태를 분리한다. 각각 하루 96회 cache miss와 실패 후 15분 backoff다.
- 주차 패턴은 기존 airport_id/observed_at cover index로 같은 요일·시간의 제한 범위만 읽고 DB에서 집계한다.
  새 주차 인덱스·수집 원문 복사·Timescale 전환을 추가하지 않는다.

## 실제 확인과 검증

- 기존 운영 키로 TAGO 도시·15개 열차 종류·서울/부산 역 목록·서울→부산 89편 정상 응답을 확인했다.
  키는 로그·문서·코드에 저장하지 않았다. 새 로컬 API가 실제 응답을 저장하고 브라우저에서 이후 편을 표시했다.
- 코레일 KTX 경부선 19역 모두 주소·전화, 유일 이름 좌표 18역을 새 API와 브라우저에서 확인했다.
- 실제 버스 서울경부→부산 47편의 정상 응답을 확인했다. 버스 제공기관의 기존 보호 간격은 줄이지 않았다.
- WSL 관리자 typecheck·229 Vitest PASS. 375/1440px 홈·도시철도·일반철도, 버스 양방향 연결, 공항 자동 조회 E2E 6개 PASS.
  실제 TAGO+코레일 새 API/DB/브라우저 E2E 1개 PASS. 설명 팝업 열기/Escape와 지도 크기·시작 위치도 검사한다.
- WSL 집중 backend43개 PASS·1개 제외, 새 공개 안내 API3개 PASS. provider SDK 전체203개 PASS·2개 opt-in 제외,
  커버리지91.99%·mypy PASS. 최종 SHA 전체/PG/Compose/CI와 리뷰 상태는 후속 실행 결과로 갱신한다.
- 첫 Compose UI 검사는 이미지 NODE_ENV=production 상속으로 React act가 비활성화되어 실패했다.
  소스 실패로 판정하지 않고 테스트 전용 NODE_ENV=test로 재실행한다.

## 미완료 수용

1. 전국 버스 전체 연결 원천과 미확인 터미널 좌표. 현재 저장 연결만 제공하며 미조회 노선을 미운행으로 확정하지 않는다.
2. 고속도로 선택 노선 선형 속도 지도는 SDK의 같은 LINK_INFO 경로·속도로 구현하고 실제 UI까지 검증했다.
   전국 완전성·SHP 전국 오프라인 운영·KREX와 ITS 코드 교차표는 제공하지 않으며 이름으로 추정 결합하지 않는다.
3. 최종 전체 CI·James/Popper·격리 PostgreSQL/Compose·통합 담당의 빌드·운영 배포와 실화면 수용.
   운영 반영 전에는 새 시간표 수집량·전국 범위·성능 향상을 달성했다고 표시하지 않는다.

## 독립 리뷰 후속과 격리 검증

- James 지적: 취소한 철도 조회의 pending 복귀, embedded 상세의 키보드 진입/닫기 복원을 수정했다.
  버스 목록의 대기/실패와 정상 빈 결과도 구분한다. 375/1440px 조건 왕복·Enter/Escape·포커스 복원과
  버스 대기/오류 회귀를 포함한 E2E **7개 PASS**다.
- Popper 지적: TAGO cache miss마다 초기화하던 버킷을 router/worker의 `AsyncTokenBucket`으로 공유한다.
  서로 다른 miss 사이 1초 간격 회귀와 catalog city membership 검증을 추가했다. 일반철도·startup guard 집중 **12개 PASS**다.
- 격리 WSL Docker PostgreSQL16에서 migration0034 upgrade와 alembic check PASS,
  rail/bus/parking/KRIC/lifespan 집중 **53개 PASS**다. Docker 관리자229개도 test 환경에서 PASS다.
- 새 schema를 올린 PG 검사에서 startup의 옛 head0033 불일치를 발견해0034로 맞췄다. 보호를 제거하지 않았다.
- 첫 전체 SQLite 검사는 백엔드의 비어 있는 scripts 캐시 디렉터리 때문에 fixture 루트 탐지가 실패했다.
  원본 코드는 바꾸지 않고 격리 mirror의 빈 디렉터리를 제거한 뒤 전체 회귀를 계속 실행 중이다.
- SDK PR12의 Python3.11/3.12/3.13·typecheck CI와 최종5bf0e616 James/Popper 재리뷰에서 잔여P0/P1/P2없음.
- Dagster job 실행 이력 링크는 공식 UI의 `/locations/<location>/jobs/<job>/runs` 계약을 사용한다.
  [공식 경로](https://github.com/dagster-io/dagster/blob/master/js_modules/ui-core/src/pipelines/PipelineRoot.tsx)를 대조했다.
- 전체 CI/정확 최종SHA 재리뷰·수용은 진행 중이며 운영 빌드·배포를 재개하지 않는다.

## ITS 선택 도로 지도와 후속 검증

- 공개 ITS `polylineOl.js`의 EPSG:4326 사용을 대조했고 파싱·좌표 검증은 SDK PR4에 추가했다.
  [SDK PR4](https://github.com/digitie/python-krits-api/pull/4)는 offline157개·live12개·strict mypy와
  Python3.11~3.14/패키징 CI PASS다. 독립 James/Popper 리뷰의 잔여 P0/P1/P2는 없다.
- 실제 새 로컬 API로73개 고속도로와 경부361링크/361경로를 받았다. 원문과 동일한 링크별 속도를 색으로 표시하고,
  경로 미제공 항목도 목록에 남긴다. 지도 건수는 실제 렌더된 링크를 중복 없이 센다.
- 375/1440px 실제 ITS→API→브라우저2개 PASS(32.1초): 지도 선 렌더, 모바일 지도 시작 높이·면적,
  Enter 상세 진입·Escape/포커스 복원·목록 선택→지도 이동·i 설명·가로 넘침을 검증했다.
- GeoJSON source가 영구 pending인 문제를 실제 브라우저에서 발견했다. Map의 기존 worker/shared 정적 파일 복사와
  setWorkerUrl 배선을 재사용하고 Docker runner의 public 복사를 보강했다. 설치본 파일 생성까지4개 회귀로 검사한다.
  [MapLibre 공식 worker 설정](https://maplibre.org/maplibre-gl-js/docs/#esm)을 함께 대조했다.
- 최종 WSL 관리자 타입·lint·235 Vitest PASS, 신규 ITS API5개와 일반철도/startup12개 합계17개 PASS다.
  cache 재사용·membership·0속도·stale/오류 구분·상한·timeout cleanup/backoff·한국 날짜 예산 복원을 검사했다.
- 이전 전체 SQLite 검사는 /tmp RAM tmpfs 용량 부족으로 실패했으므로 성공 근거에서 제외했다.
  소유한 미사용 mirror와 테스트 데이터를 /var/tmp로 보존 이동하고 새 전체 검사를 디스크에서 진행한다.
- 사용자가 순수 UI를 먼저 서브에이전트로 완료·배포하도록 추가 지시했다. 별도 worktree에서 기존 운영 API와
  호환되는 UI만 선별하고 승인된 관리자 웹만 교체한다. 이 ITS API/선형 지도와 미배포 schema0034는 별도 통합 대상이다.
- 이후 사용자가 빌드 담당을 위해 main 머지를 먼저 요청했다. UI PR127을 main `34f8fab120dc5013a74c4b8759883e8357ba86e9`로 머지했다.
  순수 UI의 WSL/Docker241·UI10·Firefox1·두 리뷰와 최종 head UI CI를 확인했고 동일 backend tree의 성공 main CI를 재사용했다.
  이 문서의 신규 backend/ITS는 PR126에 남기며 UI의 운영 교체 완료를 뜻하지 않는다.
- PR124의 보안 정합을 관리자 소비자에도 보존했다. Next16.4.3/React19.3.1/MapLibre6.15 등 새 잠금에서
  WSL242·타입/lint, 실제 ITS UI2(55.5초)와 교통 이용 흐름7(49초) PASS다. 격리 Docker PostgreSQL 집중23개 PASS다.
- 같은 소통 구간 재선택의 카메라/포커스 실패를 재현해 요청 번호를 분리했다. 목록→지도 준비 전에 상세를 닫아도
  마지막 카메라 요청을 보존하고, 상세 ref는 활성 탭에만 붙인다. 두 뷰포트에서 최종 위치·줌·재선택까지 검사했다.
- 전체 SQLite에서 세 SQL 단언의 첫 router 가정 회귀를 발견했다. 기존 router를 먼저 등록해 원래 순서를 보존했고
  해당3개를 WSL과 PostgreSQL에서 재검증했다. 이전 source의 전체 실행은 이 실패를 포함하므로 PASS로 세지 않는다.
- main34f8fab 통합 후 타입/lint·관리자243개와 ITS API6개 PASS다. 이전 CI의 실패7개는 같은 router 순서 가정6개와
  Firefox 수정 라이브러리1.0.1을 반영하지 않은 계약 테스트1개였다. 계약 기대값도 실제 소비 버전으로 갱신했다.
  전체 CI를 다시 확인하며, 통과 전 신규 API/ITS의 main 머지·운영 배포 완료로 보고하지 않는다.

## 최종 실행 소스와 통합 게이트

- 실행 소스 `19cabb8d602643ee77515169276bc0c47532b84f`의 CI40058502811은 backend **1108 PASS·2skip**,
  기존 웹과 관리자 UI 모두 PASS다. migration0034 upgrade/check와 OpenAPI 계약도 같은 CI에서 통과했다.
- James는 카메라/재선택/상세 포커스와 여정별 상태, Popper는 schema/정상 캐시/공유 호출 보호/버스 범위/
  주차 동일 날짜 비중/ITS 상한·취소를 독립 재검토했다. 최종 소스의 잔여 P0/P1/P2는 없다.
- main 통합 후 WSL 타입/lint·관리자243개, ITS6개와 관련 회귀25개(1skip), Docker 관리자243개와
  PostgreSQL 집중24개가 통과했다. 실제 ITS UI2·기존 이용 흐름 UI7의 소스 기능은 보존됐다.
- WSL 종료로 중단된 로컬 전체 검사와 migration 전 새 QA DB의 Docker 실행은 성공 근거에서 제외한다.
  실행 로그를 보존하고 로컬/Compose 전체 회귀를 별도 DB에서 진행한다. 운영 API/DB/수집기 교체는 없다.
- Common PR45는 main `a330315`, krits PR4는 main `65fdf78`에 머지했다. 소비자 고정 tarball/SDK 소스는
  같은 실행 내용을 유지한다. 순수 UI는 PR127/main34f8fab이고 신규 API/ITS는 PR126 통합 대상이다.
