# Map 교통 current 고정 snapshot

## 구현 범위

`GET /v1/service/exports/highway-traffic/current?limit=1000&cursor=`를 추가한다.
기존 service token 헤더·실제 peer CIDR 검사를 상속한다. `transport_map_current_enabled`
기본값은 계속 false이며, 활성화 뒤 새 정상 수집이 current head를 생성하기 전에는503이다.
기존 public API·통계·이력과 기존 service export 계약은 변경하지 않는다.

최초 페이지는 PR112의 source/scope별 성공 head와 typed current만 REPEATABLE READ로 읽는다.
이력/raw/provider를 조회하지 않는다. 수집 필터 fingerprint는 수집과 동일한 public helper를 쓴다.
400행씩 읽어 필요한 DTO만 고정 snapshot item으로 저장하며 최대20,000건/16MiB를 넘거나
head membership과 개수가 다르면 transaction을 취소한다. snapshot은 만든 15분 cache epoch의 끝+15분까지
유효하다(2026-10-27 변경, 아래 보존·동시성).
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
전역/원천 writer 잠금은 추가하지 않으며 statement_timeout10초다.
GC/admission 이후 항목 partition 경계에서15초 경과를 검사한다. 마지막 INSERT/commit을
포함한 요청 전체15초 hard deadline은 아니며 개별 DB 문장 제한과 구분한다.
만료 snapshot GC는 새 freeze 때 최대1개(한 snapshot 최대20,000항목)만 삭제한다.
페이지 reader는 동일 RR transaction에서 snapshot와 항목을 읽으므로 PostgreSQL MVCC가
동시 GC로부터 해당 읽기를 보호한다. 미만료 snapshot은 지우지 않는다.

2026-10-27 보완(설계 변경, T2/T3 공통):

- **만료 보장**: 만료 시각은 `생성 시각+15분`이 아니라 `생성 cache epoch의 끝+15분`이다
  (`snapshot_expires_at`). cache generation이 15분 epoch라서, 예전에는 epoch 끝 몇 초 전에 재사용된
  snapshot을 받은 reader가 다음 페이지에서 410을 받고 처음부터 다시 읽었다. 이제 같은 epoch 안에서 건네는
  snapshot의 남은 수명은 항상 15분 이상이고 최대 30분이다. 응답의 `snapshot_expires_at` 의미(이 시각 이후
  cursor는 410)는 그대로라 Map reader와 하위 호환이다.
- **GC 잠금 경합**: PostgreSQL에서 GC는 victim 부모 행을 `FOR UPDATE SKIP LOCKED`로 먼저 잠근다. 다른
  transaction이 지우는 중인 victim은 건너뛴다. 예전에는 다른 종류의 첫 페이지 freeze가 같은 victim을
  골라, 그 행 잠금을 쥔 채 약 8,300항목을 물질화하는 쪽을 lock_timeout 2초까지 기다리다 55P03→503을 받았다.
  이미 commit된 삭제와 겹친 RR 직렬화 실패(40001)는 기존처럼 새 RR로 한 번 재시도한다.
- **남는 위험**: 같은 종류·scope를 동시에 처음 고정하면 UNIQUE admission에서 뒤 요청이 앞 transaction의
  commit을 기다린다(물질화가 2초를 넘으면 55P03→503). 이 경로는 바꾸지 않았다. Map reader는 503을 기존처럼
  유한 재시도한다.

## 검증 정산과 운영 잔여

migration0031은 신규 작은 표만 만들고 이력 backfill을 수행하지 않는다. PR114의 두 리뷰·
정확 CI/PG·Compose·실제 TCP와 후속 parking/T3 구현 상태는 [수용 정산](reports/2026-10-23-map-t2-t3-acceptance.md)에 모았다.
운영 미배포/defaultOFF이며 source bootstrap·Map consumer UI·비용3쌍/ARM CPU·peakRAM은 남았다.
