# Map T3 철도역 참조 export

`GET /v1/service/exports/rail-stations`는 기존 service 인증·peer·공통meta와 PR116의
source spec snapshot engine을 사용한다. 기본OFF이며 schema0032에서 도입했다. 이번 보강에 새 migration/backfill은 없다.
기존 bus/ferry path/필드/cursor는 보존하고 admin mapping reader를 순수 read service로 옮긴다.

## Source 성공

### 일반철도·KTX 공개 목록 (`kric-general`)

KRIC 일반철도·KTX 보강은 [별도 수집·합성 집합 계약](reports/2026-11-09-kric-general-rail-reference.md)을 따른다.
아래 도시철도 `nationwide` scope를 유지하고 `kric-general`의 첫 성공 집합을 별도로 합친다.
일반철도 source는 `kric_general_portal`이며 공식 연결 식별자로 역을 구분한다.
`station_number`의 코레일 코드와 KRIC 도시철도 코드 필드는 혼용하지 않는다.
일반철도 권역 라벨은 운행 노선·순서가 아니며 공식 미제공 좌표는null이다.

### 도시철도 파일 (`nationwide`)

provider public `KricFileClient.get_nationwide_station_info_to_rustfs`가 검증한 dataset1294
XLSX와 StoredObject의 SHA256/byte_size receipt를 사용한다. XLSX 파싱/다운로드를 재구현하지
않는다. nonempty·중복identity·역명·최대10,000개를 확인하고 invalid/빈파일은 최대1회 재확인한다.
이전 성공25% 미만은 다시fetch해 회복된 전체파일만 사용한다. 재확인 뒤에도 급감하면 이전
성공집합을 보존한다. 최종 catalog lock 안에서 최신head denominator도 다시 확인한다.

source reference rows/head/memberPK/native terminal은 같은 transaction에서 commit한다.
native scalar ID를 먼저 보존해 rollback 뒤 만료ORM run.id를 읽지 않는다. 실패 상태는 DB
조건부 UPDATE로 옛worker가 새성공을 stale로 덮지 못한다. network fetch 동안 DB 연결은 없다.
테스트 전용 rail_fetcher 주입은 별도fixture proof로 기록하며 운영경로는 검증된 archive receipt가
필수다. 수집48시간 due 정책은 유지한다. source 실패/6일 초과는 이전 성공+stale다.

## 코드와 매핑

source identity/역명/기관·노선/역번/좌표와 nullable operator_code/line_code/station_code,
code_station_name/code_collected_at/code_active/mapping_method/mapping_revision/T1 admin을 제공한다.
코드 선행0을 보존한다. source 좌표가 미확인·국내범위 밖이면null이다. 기관/노선별 동명역을
endpoint에서 이름으로 다시 연결하지 않는다.

active KRIC FK와 저장된 automatic/manual registry를 같은 RR에서 읽는다. manual registry가
우선하고 저장FK와 대상identity가 다르면503이다. inactive/unmapped 코드는 null/active=false다.
옛 persisted FK만 있고 registry가 없으면 method=persisted로 표시하며 임의 automatic/exact로
단정하지 않는다. export 요청에서 provider/시간표/자동 매칭은 호출하지 않는다. registry는 각
bounded pass에서 한 번 읽고 코드는400개 FK batch만 읽는다.

`mapping_revision`은 저장registry의 지문이며 admin 저장의 expected_revision과 같은 토큰이
아니다(admin 토큰은 참조catalog 지문도 포함한다). 좌표·주소·FK·registry 수정은 다음 첫snapshot
DTO digest에 반영하고 기존 페이지는 만료까지 고정한다. source row.last_seen_at은 승인head와
일치해야 하므로 flagOFF legacy source 변경을 옛head로 성공 처리하지 않는다. 코드catalog는
시간표와 별도로 commit되므로 뒤 시간표 실패가 정상코드 갱신을 무효화하지 않는다.

## 검증 상태

PR117 두 독립 리뷰·정확 CI PG1070 PASS/2 SKIP, 집중 PG40 PASS와 실제 TCP 결과는
[수용 정산](reports/2026-10-23-map-t2-t3-acceptance.md)에 기록했다. 제품 기본값OFF와 별개로,
2026-11-09 운영 API·수집기의 공통flag를ON하고 공식 철도 최초 수집을 완료했다.
실제 Map 호스트 n150에서1108건의 전체 두 페이지·고유identity·source_status=ok·ETag304를 확인했다.
좌표null13건은 그대로 유지한다. [운영 정산](reports/2026-11-09-map-reference-activation.md).
같은 날 후속 KRIC 일반철도358건의 저장을 완료해 실제 Map peer에서1466건 두 페이지·고유identity·
source_status=ok·ETag304를 검산했다. 신규 좌표 미제공160건까지 전체null173건을 보존한다.
[일반철도 최종 수용](reports/2026-11-09-kric-general-rail-reference.md).
Map 적재·consumer UI와 ARM CPU/RAM 실측은 이번 검증에 포함하지 않는다.
