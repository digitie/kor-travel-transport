# Map 교통 current 고정 snapshot

## 구현 범위

`GET /v1/service/exports/highway-traffic/current?limit=1000&cursor=`를 추가한다.
기존 service token 헤더·실제 peer CIDR 검사를 상속한다. `transport_map_current_enabled`
기본값은 계속 false이며, 활성화 뒤 새 정상 수집이 current head를 생성하기 전에는503이다.
기존 public API·통계·이력과 기존 service export 계약은 변경하지 않는다.

최초 페이지는 PR112의 source/scope별 성공 head와 typed current만 REPEATABLE READ로 읽는다.
이력/raw/provider를 조회하지 않는다. 수집 필터 fingerprint는 수집과 동일한 public helper를 쓴다.
400행씩 읽어 필요한 DTO만 고정 snapshot item으로 저장하며 최대20,000건/16MiB를 넘거나
head membership과 개수가 다르면 transaction을 취소한다. snapshot은15분 유효하다.
다음 페이지는 snapshot PK+ordinal index에서 limit+1행만 읽는다. 이후 같은 history PK가
수정되거나 새 수집 head가 승격되어도 기존 snapshot DTO는 바뀌지 않는다.

## 응답 계약

`meta={generated_at,source_collected_at,source_status,item_count}`와
`snapshot_id,snapshot_expires_at,total_count,items,next_cursor,has_more`를 반환한다.
item은 identity/source/route/conzone/direction/speed/free_flow_speed/congestion_level/
observed_at/collected_at이다. 시간은 UTC aware이고 코드는 문자열로 유지한다.
마지막 실패 또는30분 초과 원천은 이전 성공 집합과 `source_status=stale`을 반환한다.
초도 미확정·membership 불일치는503이며 미확정 빈 집합을 성공 처리하지 않는다.
기존 T5가 같은scope에서 두 번의 명시total0·완결 증거로 승인한 head가0건이면,
확인된 정상0건 snapshot(total0/items[]/has_more=false)을 제공하여 기존 장소 퇴역을 전달한다.

`limit`은1~5,000이고 cursor는 경로·scope·limit·snapshot·ordinal을 HMAC으로 묶는다.
위조/범위 변경은422, 만료/GC된 정상 handle은410이다. 첫 페이지부터 재시작한다.
ETag는 DTO·snapshot 유효시각·현재 health를 포함한다. source 실패를304로 숨기지 않는다.
JSON/gzip(level1)은 DB commit/pool 반환 뒤에 생성한다. gzip 협상은 기존 parser를 재사용한다.

## 보존·동시성

같은 source 성공 generation과15분TTL epoch의 미만료 snapshot을 재사용한다.
DB UNIQUE(kind,scope,cache generation)가 항목 저장 전 admission을 보장한다. RR에서
보이지 않는 경쟁 freeze가 먼저 확정됐으면 rollback 후 새 RR로 최대1회 재시도하여 같은
snapshot을 읽는다. 추가 물질화는 하지 않는다. 연속 충돌/락대기2초 초과는503이다.
전역/원천 writer 잠금은 추가하지 않으며 statement_timeout10초·freeze wall15초다.
만료 snapshot GC는 새 freeze 때 최대1개(한 snapshot 최대20,000항목)만 삭제한다.
페이지 reader는 동일 RR transaction에서 snapshot와 항목을 읽으므로 PostgreSQL MVCC가
동시 GC로부터 해당 읽기를 보호한다. 미만료 snapshot은 지우지 않는다.

## 미완 게이트

migration0031은 신규 작은 표만 만들고 이력 backfill을 수행하지 않는다. 실제 전용PG
upgrade/downgrade/check, 비용3쌍·8300개 p50/p95/CPU·peakRAM, 전체 회귀·CI·2인 리뷰·
실제 API/UI 및 운영 수용은 결과가 확보될 때 별도로 기록한다. 이 문서는 이들 PASS를
선언하지 않는다. parking current와 T3의 source별 성공증거·고정DTO export는 후속이다.
