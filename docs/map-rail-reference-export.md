# Map T3 철도역 참조 export

`GET /v1/service/exports/rail-stations`는 기존 service 인증·peer·공통meta와 PR116의
source spec snapshot engine을 사용한다. 기본OFF/schema0032이며 새 migration/backfill은 없다.
기존 bus/ferry path/필드/cursor는 보존하고 admin mapping reader를 순수 read service로 옮긴다.

## Source 성공

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

기존 rail/mapping36 PASS, 신규rail API/빈·중복파일/leading0/manual/inactive/registry 불일치/
fetch pool0·옛페이지 보존 포함40 PASS를 WSL SQLite에서 확인했다. 전용PG/CI/두 적대리뷰/
실제API/비용·운영 gate는 진행중이며 parking·전체T2/T3·CPU/RAM 완료를 선언하지 않는다.
