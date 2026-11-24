# 요청 소요 시간 로그 읽기 (gateway access log · backend 요청 로그 · Server-Timing)

2026-11-24 Map 호출 감사(G2-03·G2-04·G2-06·RT-09·MUI-13)의 관측 공백을 메운 계약이다.
세 원천은 모두 **query string·본문·토큰·ID를 남기지 않는다.** 경로는 gateway가 `$uri`(query 없음),
backend가 route template(`/v1/service/exports/fuel-stations/{station_key}/price-history`)만 쓴다.

| 원천 | 위치 | 남는 요청 |
|---|---|---|
| 공개·export gateway(12301) | `deploy/transport-admin/api-gateway.conf.template` `log_format transport_timing` | `/health`를 뺀 모든 요청 |
| 공개 유가 gateway(12307) | `deploy/transport-fuel/api-gateway.conf.template` `log_format fuel_timing` | `/health`를 뺀 모든 요청 |
| backend 요청 로그 | `backend/app/core/read_timing.py` | `/v1/service/exports/*` 전부 + 임계 이상 모든 요청 |
| Server-Timing 응답 header | 같은 middleware | 모든 HTTP 응답 |

## gateway access log

두 gateway는 공식 nginx 이미지의 stdout으로 쓰므로 `docker logs <gateway 컨테이너>`로 읽는다.
기본 compose 이름은 `kor-travel-transport-transport-api-gateway-1`,
`kor-travel-transport-fuel-fuel-api-gateway-1`이다(운영에서는 `docker ps`로 먼저 확인한다).

```text
2026-11-24T04:09:15+00:00 192.168.1.14 "GET /v1/service/exports/fuel-stations" 200 3000170 rt=0.412 uct=0.000 uht=0.388 urt=0.405 ust=200
2026-11-24T04:08:13+00:00 192.168.1.1 "GET /v1/transport/fuel/places" 200 81234 rt=0.231 uct=0.000 uht=0.229 urt=0.230 ust=200 gz=4.71
```

| 필드 | 뜻 |
|---|---|
| `$time_iso8601` | 요청이 **끝난** 시각(nginx 기록 시점) |
| `$remote_addr` | 직전 peer. 12301 공개 경로와 12307은 앞단 HAProxy 주소일 수 있다. export는 Map(n150) 주소다 |
| `"METHOD $uri"` | 정규화된 경로. query는 없다(cursor·좌표를 남기지 않는다) |
| status, bytes | 클라이언트에 보낸 상태와 본문 bytes(압축 뒤) |
| `rt` | gateway가 요청을 받은 뒤 마지막 byte를 보낼 때까지(초). 느린 클라이언트 수신 시간이 포함된다 |
| `uct` | backend 연결 수립(초). `-`는 upstream을 부르지 않은 응답(400·403·404·preflight) |
| `uht` | backend 첫 응답 header까지(초). backend 처리 시간에 가장 가깝다 |
| `urt` | backend 응답을 끝까지 받은 시점(초) |
| `ust` | backend 상태. gateway 504/502이면 `504`·`502` 또는 연결 실패 표시가 남는다 |
| `gz` | (12307만) gzip 압축비. `-`는 압축하지 않은 응답(1KiB 미만·이미 gzip인 가격 이력·Accept-Encoding 없음) |

읽는 법:

- `rt ≈ urt`이고 `uht`가 크다 → backend가 느리다. 같은 시각의 backend `export_request`/`slow_request`로 내려간다.
- `rt ≫ urt` → backend는 끝났고 클라이언트가 천천히 받았다(모바일·대형 본문).
- `ust=504`, `rt≈30`(공개)·`120`(export) → gateway timeout. backend 로그에 같은 route가 그 뒤 200으로 끝났는지 본다
  (gateway가 끊은 뒤에도 backend가 작업을 계속한 경우).
- `uct`가 0이 아니고 커지거나 `ust=502` → backend가 연결을 받지 못했다(재기동·lifespan 대기).

export 경로의 p50/p95 예:

```bash
docker logs --since 24h kor-travel-transport-transport-api-gateway-1 2>/dev/null \
  | awk '$4 ~ /\/v1\/service\/exports\// { split($7, a, "="); print a[2] }' | sort -n \
  | awk '{ v[NR]=$1 } END { if (NR) print "n="NR, "p50="v[int(NR*0.5)+1], "p95="v[int(NR*0.95)+1] }'
```

## backend 요청 로그

`app.core.read_timing` logger의 WARNING 한 줄이다. 운영 uvicorn은 app logger에 handler를 두지 않으므로
`logging.lastResort`(stderr, 메시지만)로 나가고 시각이 붙지 않는다. 그래서 줄 안에 `start`(요청 시작 UTC)를 싣는다.
`docker logs kor-travel-transport-backend-1 2>&1 | grep -E '^(slow|export)_request '`로 읽는다.

- `export_request` — `/v1/service/exports/*` 요청이 임계 미만으로 끝났다(이 경로는 모두 남긴다).
- `slow_request` — 경로와 무관하게 `SLOW_REQUEST_THRESHOLD_MS`(기본 1000) 이상 걸렸다. `0`이면 모든 요청이 남는다.

```text
export_request route=/v1/service/exports/rail-stations method=GET status=200 start=2026-11-24T04:10:00.123Z duration_ms=84.210 sql_count=4 sql_ms=12.402 cpu_ms=61.000 loop_cpu_ms=58.000 page_builds=1 fingerprint_calculations=0 pool_ms=0.091 pool_checkouts=1 pool_connects=0 pool_checkedout=2 inflight_start=1 inflight_end=0
```

| 필드 | 뜻 |
|---|---|
| `route` | route template. 매칭 전 거절은 `unmatched` |
| `status` | 응답 상태. 응답 시작 전 취소·연결 끊김은 `none`, 처리되지 않은 예외는 `500` |
| `start` | 요청 시작 UTC(ms). gateway `$time_iso8601`은 끝난 시각이다 |
| `duration_ms` | middleware 안 전체 시간(응답 전송 포함) |
| `sql_count`, `sql_ms` | 이 요청이 실행한 문장 수와 DB 왕복 합 |
| `cpu_ms` | **프로세스 전체** CPU 차이(`process_time`). 같은 시간에 돈 주차 이력 재구성 thread·다른 요청의 CPU가 섞인다. 예전 로그와 비교하려고 그대로 둔다 |
| `loop_cpu_ms` | 이벤트 루프 thread의 CPU 차이(`thread_time`). 다른 thread 작업은 빠지지만 같은 루프에서 번갈아 돈 다른 coroutine의 CPU는 포함한다. 핸들러가 `asyncio.to_thread`로 넘긴 작업(공개 places 검증 등)도 빠진다 |
| `page_builds` | 응답 페이지 DTO를 새로 만든 횟수. 0이면 캐시·304 |
| `fingerprint_calculations` | 참조 export 입력 지문 계산 횟수. 0=메모 적중, 1 이상=지문 재계산(배포 직후·입력 변경) |
| `pool_ms` | DB 풀에서 연결을 받기까지 걸린 시간 합(대기열 대기 + 새 연결 + pre-ping). SQL 시간 밖이다 |
| `pool_checkouts` | 이 요청의 연결 checkout 수 |
| `pool_connects` | 이 요청 중 새로 연 DB 연결 수. 0이 아니면 `pool_ms`에 연결 수립 비용이 있다 |
| `pool_checkedout` | 연결을 받은 직후 풀의 사용 중 연결 수 최댓값(자기 포함). API 풀 상한은 10(5+5). NullPool이면 `none` |
| `inflight_start`, `inflight_end` | 시작 시점 동시 요청 수(자기 포함), 끝난 시점에 남은 다른 요청 수 |

지연 분해:

1. `pool_ms`가 크다 → 풀 고갈. `pool_checkedout`이 10 근처이고 `inflight_start`가 크면 무거운 요청이 풀을 잡고 있다.
   풀 고갈 timeout(30초)으로 실패한 요청도 기다린 시간이 `pool_ms`에 남는다.
2. `sql_ms`가 크다 → DB. 같은 route의 EXPLAIN으로 내려간다.
3. `duration_ms − sql_ms − pool_ms`가 크고 `loop_cpu_ms`가 그 대부분 → 이벤트 루프의 Python CPU(직렬화·DTO 구성).
   `inflight_start`가 1이면 이 요청 자신의 비용으로 읽는다.
4. 3의 차이가 큰데 `loop_cpu_ms`는 작고 `cpu_ms`가 크다 → 다른 thread(이력 재구성 등)가 CPU·GIL을 쓰는 동안 기다렸다.
5. 참조 export에서 `fingerprint_calculations`·`page_builds`가 0이 아니고 1초 이상 → cold(배포 직후 artifact 재구성).

한계: 503의 원인(현재 집합 없음·예산 초과·lock)은 상태 코드로만 남고 사유 코드는 아직 없다. 오래 걸린 503은
`duration_ms`로만 구분한다. 일일 로그 양은 export 하루 약 800줄(Map T1 매시 약 32~33건 기준)과 임계 이상 요청 수다.

## Server-Timing 응답 header

`app;dur`, `sql;dur`, `sql_count;desc`, `cpu;dur`, `page_builds;desc`, `fingerprint_calculations;desc` 뒤에
`pool;dur`, `loop_cpu;dur`를 덧붙인다. 기존 필드의 이름·순서는 바꾸지 않는다. 뜻은 위 표와 같고 응답 header를
보내는 시점까지의 값이다(본문 전송 시간은 빠진다).

## 공개 gateway 가드레일

- 공개 장소 조회의 `limit`은 두 gateway에서 900을 넘지 않는다. 12301 `location = /v1/transport/features/places`와
  12307 `location = /v1/transport/fuel/places`가 `$arg_limit`을 판정해 upstream query **끝**에 `&limit=<값>`을 붙인다
  (Starlette는 반복 query의 마지막 값을 쓴다). 생략은 900, 1~900은 그대로, 900 초과 정수는 900, 그 밖은 400
  problem+json이다. 관리 지도(최대 900)·공개 유가(300)는 영향이 없고, 관리 목록 검색(최대 5000)은 관리 BFF가
  backend 12302를 직접 부르므로 gateway를 지나지 않는다. backend 자체 상한(5000)은 그대로다.
- export location은 `proxy_buffers 64 32k`(요청당 최대 2MiB)와 `proxy_max_temp_file_size 0`이다. 주유소 500행
  페이지(약 1.2MB 비압축)가 컨테이너 쓰기 계층의 `proxy_temp` 파일로 내려가지 않고, 더 큰 본문은 소비자 속도로
  그대로 흘린다. 기존 설정에서 보이던 `an upstream response is buffered to a temporary file` 경고가 없어야 한다.
- 공개 유가 gateway는 JSON을 gzip level 1(1KiB 이상, `gzip_proxied any`, `Vary: Accept-Encoding`)로 압축한다.
  backend가 이미 gzip으로 준 가격 이력은 다시 압축하지 않는다. 압축 효과는 access log `gz`로 본다.
- IP별 `limit_req`·`limit_conn`은 두지 않는다. 공개 유가 사용자는 모바일 통신사 NAT 뒤에서 같은 주소를 공유하므로
  주소별 제한은 정상 사용자를 막는다. 무거운 요청은 위 `limit` 상한과 backend places 검증의 `CapacityLimiter(2)`(`fuel_map_limiter`)로 묶는다.
