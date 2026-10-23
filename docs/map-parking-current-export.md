# Map T2 공항 주차장 현재 상태 export

`GET /v1/service/exports/parking/current`는 기존 service token/peer 검사, 공통meta,
고정snapshot/cursor/15분TTL/gzip/ETag/최대5000개 페이지를 재사용한다. 기본 flagOFF다.
source별 complete membership가 모두 준비되어야 첫snapshot을 만든다. 이후 원천 실패는
이전 typed current와 stale을 제공하며, 초도집합이 없으면503이다.

## 원천 승인

python-krairport-api PR10의 public `parking_raw_set(provider=...,page_size=100,max_pages=20)`을
직접 호출한다. Transport에서 HTTP·원천 total/page 파싱/페이지 순회를 다시 만들지 않는다.
기존 raw/status/fee API와 기본 flagOFF collector는 유지한다. SDK total 필수/고정total,
페이지수신량/반복페이지/byte상한과 Transport의 업무 identity·필수값·중복·미래시각을 검증한다.
전체raw에서 해석되지 않은 행이 있으면 보류한다. KAC는 설정 공항으로 필터한 source scope를
hash하고 ICN scope와 분리한다. 빈/오류/이전성공25%미만은1회 다시받고 미확인 시 이전집합을
보존한다. 서로 다른 source의 성공과 요금수집 성공은 분리한다.

native run을 먼저 commit하고 이전head scalar를 읽은 다음 session.rollback하여 모든 원천
network 대기 전에 업무 DB pool을 반환한다. PG advisory owner lease 한 연결은 정상 수집
전체의 동시실행 방지를 위해 유지된다. raw/기존이력/typed현재값/head와 native terminal은
마지막 transaction에서 확정한다. 후기 저장오류는 pointer/head를 함께 rollback하고 조건부
실패 UPDATE로 기존head를 stale로 표시한다. scope·run순서 조건으로 옛worker 실패가 새head나
다른source의 성공을 덮지 않는다. 실패 raw도 기존 raw 보존 경계에 남긴다.

## 작은 현재 상태와 위치 의미

schema0033은 `parking_current` 작은typed표만 추가하고 이력을 backfill하지 않는다.
현재source/scope/lot PK를 사용하고 새generation에서 빠진 현재행은 같은transaction에서 정리한다.
이력 INSERT가 replay/unique경합으로 skip돼도 기존 저장 함수에서 받은 실제lot PK를 사용해
membership을 확정한다. legacy import lot ID와 live lot ID가 달라도 이름 재매칭을 export에서
다시 하지 않는다. 늦은 관측은 최신 값을 덮지 않는다.

DTO는 source/airport_code/lot_code/name, total/occupied/available, observed_at/collected_at을
제공한다. 좌표는 SDK 번들 공항 좌표이므로 `location_source=airport_anchor`다. 주차장 입구의
정밀좌표로 사용하면 안 된다. source_collected_at은 승인된 관측집합의 가장 이른 observed_at이며,
15분을 넘으면 stale이다. 수집 시도 시각은 별도 head.last_attempt_at에 남긴다.
raw/이력표 SELECT 없이 작은현재표만 읽고 API 응답 직렬화 전에 DB transaction을 반환한다.

## Map 인계와 운영 경계

Map은 첫 응답의 snapshot_id/next_cursor/limit을 유지해 끝까지 읽는다. 410이면 처음부터
재시작하고 stale을 UI에 반영한다. endpoint가503인 초기상태에서 기존 Map집합을 비우지 않는다.
마이그레이션33 후 source의 정상 complete 수집과 flagON 검증이 필요하다. 운영 적용은 root가
활성 수집 run 종료/worker확인·Transport instigator보존 절차와 조율한다. 이 PR은 자동 배포하지 않는다.

검증 진행중: SQLite source/API 및 기존collector28PASS, OpenAPI/TS갱신. schema왕복/PG집중,
실제TCP/Compose/최종CI/두적대리뷰가 남아 있으므로 운영성공·CPU/RAM개선완료를 선언하지 않는다.
