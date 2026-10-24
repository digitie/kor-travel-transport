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
2. 고속도로 선형·표준노드링크 기반 속도 지도. 현재 돌발 좌표 지도와 구간 속도 표·통계는 구현됐으나 선로형 소통 지도는 아니다.
   별도 `python-krits-api` 진행 작업과 좌표계·링크 ID 계약을 맞춰야 하며 KREX conzone과 ITS link를 이름으로 추정 결합하지 않는다.
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
