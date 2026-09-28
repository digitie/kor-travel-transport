# 성능 기준

## 첫 화면

첫 화면은 `GET /v1/dashboard/bootstrap` 한 번으로 공항·주차 현황·수집기 상태·공휴일 요약을 받는다. 기존 개별 endpoint는 하위 호환과 직접 진단용으로 유지한다. `/v1/airports`는 `selectinload`로 주차장 목록을 한 번에 읽어 공항 수만큼 반복하던 N+1 조회를 제거했다.

## 지연 분석

분석 섹션은 viewport 근처에 들어올 때만 요청한다. 데이터베이스 기반 5개 분석을 `GET /v1/dashboard/analytics`로 묶고, 외부 API가 느려도 주차 분석을 막지 않도록 비행편은 별도 요청과 6초 client timeout을 유지한다. 기본 기간의 시계열·요일·임계치 결과는 `analytics_caches`를 사용한다.

## PostgreSQL 인덱스

- `parking_snapshots (airport_id, parking_lot_id, observed_at DESC, id DESC)` — 주차장별 최신 관측
- `parking_snapshots (airport_id, parking_lot_id, observed_at)` — 기간 분석
- `parking_snapshots (collected_at)` — 수집 신선도 확인
- `parking_snapshots (collection_run_id)` — 실행과 원본 추적
- `highway_traffic_snapshots (route_no, observed_at, direction) INCLUDE (speed, free_flow_speed)` —
  노선 동일성·기간 범위로 좁혀진 고속도로 통계의 index-only 집계

운영에서는 `EXPLAIN (ANALYZE, BUFFERS)`로 7일 시계열과 current query를 확인하고, 임의로 인덱스를 추가하지 말고 `docs/journal.md`에 근거를 기록한다.

`0008_transport_route_stats`는 `CREATE INDEX CONCURRENTLY`를 사용한다. 배포가 DDL 수행 중
중단되면 PostgreSQL은 같은 이름의 invalid index를 남길 수 있으며 `IF NOT EXISTS`는 그 index를
수리하지 않고 생성을 건너뛴다. 다음 배포 전 운영자가 `pg_index.indisvalid`를 확인하고, invalid이면
해당 index만 `DROP INDEX CONCURRENTLY`한 뒤 migration을 재실행한다. 이 절차는 정상 index를
무단 삭제하거나 전체 schema를 되돌리지 않는다.

## 교통 통계의 집계 상한과 유가 정비

- 통계 cache miss는 `TRANSPORT_STATISTICS_TIMEOUT_SECONDS=20` 안에 집계를 마치며,
  같은 키 대기 시간도 포함한다. 초과 시 실제 쿼리를 취소·rollback하고 슬롯을 반환한 뒤
  504를 반환한다. 실패 결과는 캐시하지 않고 대기자가 남아 있는 lock은 유지한다.
  설정 상한은 25초로 제한해 관리 UI의 30초 upstream 제한보다 먼저 종료한다.
- `0015_fuel_statistics_priced`는 가격 없는 행을 제외한 covering index를 concurrent로
  생성한 뒤 기존 전체 가격 통계 index만 제거한다. 관측 원본·유일 키·응답 계산은 유지한다.
  n150 7일 표본의 유효 행은 141,776개인데 이전 index는 NULL 가격 176,419개도 읽었다.
  DDL 연결에 잠금 3초·문장 180초 제한을 직접 적용한다. asyncpg에는 `PGOPTIONS`가
  적용되지 않는다. invalid index 실검증이 필요하므로 이 revision은 온라인 실행만
  지원하며 `--sql`은 명시적인 오류로 중단한다.
- 가격 테이블의 auto vacuum/analyze scale factor를 0.02로 조정한다. 전체 PostgreSQL
  설정이나 다른 앱 테이블은 변경하지 않는다. 중단된 DDL의 invalid index는 자동으로
  정상 취급하지 않으며 이름을 확인한 뒤 그 index만 정리하고 migration을 재실행한다.
- 테이블 복원·대량 적재 뒤에는 `EXPLAIN (ANALYZE, BUFFERS)`와 `relallvisible`을 확인한다.
  일반 `VACUUM (ANALYZE, TRUNCATE FALSE, PARALLEL 0)`는 데이터를 삭제하거나 파일을
  재작성하지 않는다. 공유 서버에서는 lock/statement timeout·cost delay를 지정한다.
  긴 index cleanup이 상한을 넘으면 visibility 정비만 별도로 하고, index 정리를 완료했다고
  보고하지 않는다. [`PostgreSQL 정기 정비`](https://www.postgresql.org/docs/17/routine-vacuuming.html) 참조.

### 배포 전후 확인

1. 유가 2/7/10일 cold·warm 계획/응답 시간, heap fetch, 버린 NULL 가격 행 수를 구분한다.
2. 실제 PostgreSQL `pg_sleep` 취소 뒤 같은 session의 후속 조회와 집계 슬롯 반환을 검사한다.
3. concurrent index 생성 성공/valid를 확인한 뒤만 구 index를 제거한다. rollback은 새 runtime을
   내리기 전에 `0014_kric_timetables`로 downgrade하고 이전 이미지를 재기동한다.

## 수용 기준

- bootstrap 성공 후 주차 현황이 표시되고 외부 비행편 지연으로 loading 전체가 붙잡히지 않는다.
- 모바일에서 page-level 가로 스크롤은 없고, 큰 테이블/차트만 자체 스크롤한다.
- 14 운영에서 `/health` 200, `/v1/parking/current`, `/v1/dashboard/bootstrap`, `/v1/dashboard/analytics`가 정상 응답한다.
