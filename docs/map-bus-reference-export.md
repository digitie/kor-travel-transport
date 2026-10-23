# Map T3 버스 터미널 참조 export

`GET /v1/service/exports/bus-terminals`에 기존 service 인증·peer 검사를 그대로 사용한다.
현재 core 참조의 소유 범위는 TAGO express/intercity 각각이다. 두 source 모두 새 완결
성공이 있어야 초도 snapshot을 만든다. 전역 CollectionRun 성공을 다른 source의 신선도로
대체하지 않는다. `transport_map_current_enabled` 기본OFF 유지, migration0032이며 backfill 없음.

source별 총건수·page순서·page크기·각page 실제행수·고유코드를 provider public typed page
API에서 확인한다. 잘못된/빈 응답은 최대1회 재확인하고 실패하면 이전 성공집합을 유지한다.
이전 성공25% 미만은 두 번의 완결 metadata와 동일 identity 집합이 확인된 nonempty만 승인한다.
이름/코드 누락·중복은 성공으로 내보내지 않는다. 고속/시외 전체 fetch와 보조기준정보 fetch를
마친 뒤 reference rows+source head/memberIDs+native success를 하나의 transaction에 확정한다.
외부 fetch 동안 DB pool을 반환한다. 후기 저장 실패는 rollback하고 scalar native run ID로
실패를 기록한다. 만료 ORM run.id 재접근을 하지 않는다.

작은 `reference_export_states`는 source별 generation/run순서/실제확인시각/최대10,000개
memberPK/완결 receipt/최근실패를 보존한다. generic kind/scope 키이며 원천 row 정본은 유지한다.
원천 실패는 마지막 성공 generation/memberIDs/확인시각을 전진시키지 않고 last_error만 남긴다.
기존 좌표보존·이름/도시 변경 시 무효화·관리자 수동좌표 우선 정책을 유지한다.

첫 HTTP snapshot은 성공 memberIDs만400개씩 읽고 exact좌표 T1 admin을 일괄 조회한다.
raw 전체를 Python에 싣지 않고 manual revision만 SQL projection으로 읽는다. 수동좌표/주소
변경도 다음 첫 snapshot에 즉시 반영하도록 DTO content digest를 계산한다. 재사용 판단을
source last_seen만으로 하지 않는다. 동일 RR에서 두 번째 bounded pass로 item을 저장하므로
전체 DTO 목록을 메모리에 유지하지 않는다. 최대20,000개/16MiB/15초,15분TTL이다.

응답은 공통 meta와 snapshot_id/expires/total_count/items/next_cursor/has_more다.
identity는 source+service_type+terminal_id로 고속/시외 같은코드가 충돌하지 않는다.
null 좌표를0,0으로 바꾸지 않는다. 실제좌표와 reverse coordinate_key가 같은 경우에만 admin을
붙인다. source실패 또는9일 초과는 이전집합+stale이며 이전 HTTP 페이지의 DTO는 유지한다.
limit1~5000·HMAC cursor·410/422·gzip/ETag·DB 반환 후 압축은 traffic과 같은 계약이다.

현재 WSL 집중14 PASS이며 전체PG/CI/Docker/2리뷰/실제API/UI/비용·운영 수용은 진행 중이다.
이 문서와 PR은 parking/ferry/rail T2/T3 완료를 선언하지 않는다.
