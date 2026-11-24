# 요청 소요 시간 로그 읽기 (gateway access log · backend 요청 로그 · Server-Timing)

2026-11-24 Map 호출 감사의 관측 공백(G2-03–06, RT-09, MUI-13)과 공개 gateway 가드레일(MUI-08 limit 상한,
MUI-11 압축)을 메운 계약이다. 세 원천 모두 **query string·본문·토큰을 남기지 않는다.**
경로 표기는 원천마다 다르다.

- gateway: 클라이언트가 보낸 경로를 디코드하지 않은 채 query만 떼어 남긴다. 그래서 경로 안의 공개 식별자
  (`/v1/service/exports/fuel-stations/opinet%3AA0001/price-history`의 station_key,
  `/v1/transport/parking-lots/12`, `/v1/transport/fuel/stations/7/price-history`의 id)는 **남는다.**
- backend: route template(`/v1/service/exports/fuel-stations/{station_key}/price-history`)만 남기고 ID는 남기지 않는다.

| 원천 | 위치 | 남는 요청 |
|---|---|---|
| 공개·export gateway(12301) | `deploy/transport-admin/api-gateway.conf.template` `log_format transport_timing` | `/health`를 뺀 모든 요청 |
| 공개 유가 gateway(12307) | `deploy/transport-fuel/api-gateway.conf.template` `log_format fuel_timing` | `/health`를 뺀 모든 요청 |
| backend 요청 로그 | `backend/app/core/read_timing.py` | `/v1/service/exports/*` 전부 + 임계 이상 모든 요청 |
| Server-Timing 응답 header | 같은 middleware | 모든 HTTP 응답(공개 gateway는 응답에서 뺀다) |

## gateway access log

두 gateway는 공식 nginx 이미지의 stdout으로 쓰므로 `docker logs <gateway 컨테이너>`로 읽는다.
기본 compose 이름은 `kor-travel-transport-transport-api-gateway-1`,
`kor-travel-transport-fuel-fuel-api-gateway-1`이다(운영에서는 `docker ps`로 먼저 확인한다).

```text
2026-11-24T04:09:15+00:00 192.168.1.14 "GET /v1/service/exports/fuel-stations" 200 3000170 rt=0.412 uct=0.000 uht=0.388 urt=0.405 ust=200
2026-11-24T04:08:13+00:00 127.0.0.1 "GET /v1/transport/fuel/places" 200 412345 rt=0.231 uct=0.000 uht=0.229 urt=0.230 ust=200 gz=-
2026-11-24T04:08:14+00:00 192.168.1.1 "GET /v1/transport/fuel/places" 200 81234 rt=0.240 uct=0.000 uht=0.229 urt=0.230 ust=200 gz=4.71
```

| 필드 | 뜻 |
|---|---|
| `$time_iso8601` | 요청이 **끝난** 시각(nginx 기록 시점) |
| `$remote_addr` | 직전 peer. 12301 공개 경로는 앞단 HAProxy 주소일 수 있고, export는 Map(n150) 주소다. 12307에서 공개 유가 화면 요청은 같은 호스트의 fuel-web BFF가 보내므로 `127.0.0.1`이고, 그 밖의 주소는 `fuel-api` 직접 호출이다 |
| `"METHOD 경로"` | 클라이언트가 보낸 경로(디코드 전, query 제외). nginx 1.21.1+는 요청 줄의 공백을 거절하므로 이 값에는 공백이 없고 필드 위치가 고정된다. `"`·제어 문자는 nginx 기본 escape(`\x22`)로 남는다 |
| status, bytes | 클라이언트에 보낸 상태와 본문 bytes(압축 뒤) |
| `rt` | gateway가 요청을 받은 뒤 마지막 byte를 보낼 때까지(초). 느린 클라이언트 수신 시간이 포함된다 |
| `uct` | backend 연결 수립(초). `-`는 upstream을 부르지 않은 응답(403·404·422 limit 거절·export 503 동시 상한·preflight) |
| `uht` | backend 첫 응답 header까지(초). backend 처리 시간에 가장 가깝다 |
| `urt` | backend 응답을 끝까지 받은 시점(초) |
| `ust` | backend 상태. gateway 504/502이면 `504`·`502` 또는 연결 실패 표시가 남는다 |
| `gz` | (12307만) gzip 압축비. `-`는 압축하지 않은 응답이다: 공개 UI BFF(identity 요청), 1KiB 미만, 이미 gzip인 가격 이력, `Accept-Encoding` 없음, 200·403·404가 아닌 상태(nginx gzip은 이 셋만 압축한다) |

읽는 법:

- `rt ≈ urt`이고 `uht`가 크다 → backend가 느리다. 같은 시각의 backend `export_request`/`slow_request`로 내려간다.
- `rt ≫ urt` → backend는 끝났고 클라이언트가 천천히 받았다(모바일·대형 본문).
- `ust=504`, `rt≈30`(공개)·`120`(export) → gateway timeout. backend 로그에 같은 route가 그 뒤 200으로 끝났는지 본다
  (gateway가 끊은 뒤에도 backend가 작업을 계속한 경우).
- `uct`가 0이 아니고 커지거나 `ust=502` → backend가 연결을 받지 못했다(재기동·lifespan 대기).
- export `503`이고 `uct=-` → gateway 동시 상한(아래 가드레일) 거절이다. `ust`가 `503`이면 backend의 503(ADR-013)이다.

export 경로의 p50/p95 예(필드 위치 대신 `"GET /v1/service/exports/`와 `rt=`를 문자열로 찾는다):

```bash
docker logs --since 24h kor-travel-transport-transport-api-gateway-1 2>/dev/null \
  | awk 'index($0, "\"GET /v1/service/exports/") && match($0, / rt=[0-9.]+/) { print substr($0, RSTART + 4, RLENGTH - 4) }' \
  | sort -n \
  | awk '{ v[NR]=$1 } END { if (NR) print "n="NR, "p50="v[int(NR*0.5)+1], "p95="v[int(NR*0.95)+1] }'
```

## backend 요청 로그

`app.core.read_timing` logger의 WARNING 한 줄이다. 운영 uvicorn은 app logger에 handler를 두지 않으므로
`logging.lastResort`(stderr, 메시지만)로 나가고 시각이 붙지 않는다. 그래서 줄 안에 `start`(요청 시작 UTC)를 싣는다.
`docker logs kor-travel-transport-backend-1 2>&1 | grep -E '^(slow|export)_request '`로 읽는다.

- `export_request` — `/v1/service/exports/*` 요청이 임계 미만으로 끝났다(이 경로는 모두 남긴다).
- `slow_request` — 경로와 무관하게 `SLOW_REQUEST_THRESHOLD_MS`(기본 1000) 이상 걸렸다.

임계 바꾸기: 운영 호스트의 추적하지 않는 `.env.prod`에 `SLOW_REQUEST_THRESHOLD_MS=<ms>`를 두고 backend만
재생성한다(배포 런북의 `up -d --no-build --no-deps --force-recreate backend` 절차). 값은 기동 때 한 번 읽는다.
`0`이면 Docker healthcheck의 `/health`(45초마다)와 공개 지도·유가 조회까지 **모든 요청**이 한 줄씩 남으므로
짧은 진단에만 쓰고 원래 값으로 되돌린다. 음수는 기동 시 설정 검증에서 거절된다.

```text
export_request route=/v1/service/exports/rail-stations method=GET status=200 start=2026-11-24T04:10:00.123Z duration_ms=84.210 sql_count=4 sql_ms=12.402 cpu_ms=61.000 loop_cpu_ms=58.000 page_builds=1 fingerprint_calculations=0 pool_ms=0.091 pool_checkouts=1 pool_connects=0 pool_checkedout=2 inflight_start=1 inflight_end=0 error=none
```

| 필드 | 뜻 |
|---|---|
| `route` | route template. router가 고르지 못한 요청(404 등)은 `unmatched`, 마지막 fallback mount(`app.mount("/", 공개 유가 MCP)`, 실제 경로는 `/mcp`)는 `/*` |
| `status` | 응답 상태. 응답 시작 전 취소·연결 끊김은 `none`, 응답 시작 전 처리되지 않은 예외는 `500` |
| `start` | 요청 시작 UTC(ms). gateway `$time_iso8601`은 끝난 시각이다 |
| `duration_ms` | middleware 안 전체 시간(응답 전송 포함) |
| `sql_count`, `sql_ms` | 이 요청이 실행한 문장 수와 DB 왕복 합 |
| `cpu_ms` | **프로세스 전체** CPU 차이(`process_time`). 같은 시간에 돈 주차 이력 재구성 thread·다른 요청의 CPU가 섞인다. 예전 로그와 비교하려고 그대로 둔다 |
| `loop_cpu_ms` | 이벤트 루프 thread의 CPU 차이(`thread_time`). 다른 thread 작업은 빠지지만 같은 루프에서 번갈아 돈 다른 coroutine의 CPU는 포함한다. 핸들러가 worker thread로 넘긴 자기 작업도 빠진다: 공개 places 검증(`fuel_map_limiter`), T1 export 본문 구성(DTO·JSON·gzip, `RENDER_CONCURRENCY` 2) |
| `page_builds` | places 페이지 캐시·참조 export(T2·T3)에서 응답 페이지를 새로 만든 횟수. 0이면 캐시·304. T1 export(주유소·휴게소·돌발·공항)는 세지 않으므로 항상 0이다 |
| `fingerprint_calculations` | 참조 export 입력 지문 계산 횟수. 0=메모 적중, 1 이상=지문 재계산(배포 직후·입력 변경) |
| `pool_ms` | DB 풀에서 연결을 받기까지 걸린 시간 합(대기열 대기 + 새 연결 + pre-ping). SQL 시간 밖이다 |
| `pool_checkouts` | 이 요청의 연결 checkout 수 |
| `pool_connects` | 이 요청 중 새로 연 DB 연결 수. 0이 아니면 `pool_ms`에 연결 수립 비용이 있다 |
| `pool_checkedout` | 연결을 받은 직후 풀의 사용 중 연결 수 최댓값(자기 포함). API 풀 상한은 10(5+5). NullPool이면 `none` |
| `inflight_start`, `inflight_end` | 시작 시점 동시 요청 수(자기 포함), 끝난 시점에 남은 다른 요청 수 |
| `error` | 요청 처리 중 올라온 예외 class(`none`이면 없음). 응답을 시작한 뒤(본문 전송 중) 난 예외는 `status=200 error=<class>`로 남는다. 예외 메시지는 SQL·접속정보를 담을 수 있어 남기지 않는다 |

지연 분해:

1. `pool_ms`가 크다 → 풀 고갈. `pool_checkedout`이 10 근처이고 `inflight_start`가 크면 무거운 요청이 풀을 잡고 있다.
   풀 고갈 timeout(30초)으로 실패한 요청도 기다린 시간이 `pool_ms`에 남는다.
2. `sql_ms`가 크다 → DB. 같은 route의 EXPLAIN으로 내려간다.
3. `duration_ms − sql_ms − pool_ms`가 크고 `loop_cpu_ms`가 그 대부분 → 이벤트 루프의 Python CPU(직렬화·DTO 구성).
   `inflight_start`가 1이면 이 요청 자신의 비용으로 읽는다.
4. 3의 차이가 큰데 `loop_cpu_ms`는 작고 `cpu_ms`가 크다 → worker thread 작업이다. T1 export와 공개 places는 먼저
   자기 본문 구성·검증 thread(위 `loop_cpu_ms` 설명)로 읽고, 구성 slot 대기(T1 최대 5초)도 `duration_ms`에 들어간다.
   그 밖의 경로이거나 `inflight_start`가 크면 다른 thread(이력 재구성 등)가 CPU·GIL을 쓰는 동안 기다린 것이다.
5. 참조 export에서 `fingerprint_calculations`·`page_builds`가 0이 아니고 1초 이상 → cold(배포 직후 artifact 재구성).

계측이 어느 요청에 붙는지(context 귀속):

- 계수는 요청마다 만든 `ReadTiming`을 `contextvars`로 들고 다닌다. 요청 처리 중 만든 task·thread
  (`asyncio.create_task`·`asyncio.to_thread`·anyio `to_thread.run_sync`·single-flight leader 작업)는 만들 때의
  context를 복사하므로, 그 task의 SQL·풀
  대기·page build는 **그 task를 만든 요청**에 더해진다. 같은 계산을 기다리기만 한 follower 요청에는 더해지지 않는다
  (follower는 `duration_ms`만 길고 `sql_ms`는 작다).
- task가 만든 요청보다 오래 돌면, 요청 로그 한 줄이 이미 나간 뒤의 계수는 어디에도 남지 않는다.
- 요청 밖 작업(기동 warm, Dagster, 이력 재구성 thread)은 요청 계수에 들어가지 않고 `cpu_ms`(프로세스 전체)에만 섞인다.

한계: 503의 원인(현재 집합 없음·예산 초과·lock·T1 구성 slot·요청 상한)은 이 로그에 상태 코드로만 남고 사유 코드는 없다
(T1 503의 `Retry-After` 10/60과 응답 본문으로 구분한다, ADR-013 개정 2026-11-24). 오래 걸린 503은
`duration_ms`로만 구분한다. 일일 로그 양은 export 하루 약 800줄(Map T1 매시 약 32~33건 기준)과 임계 이상 요청 수다.

## Server-Timing 응답 header

`app;dur`, `sql;dur`, `sql_count;desc`, `cpu;dur`, `page_builds;desc`, `fingerprint_calculations;desc` 뒤에
`pool;dur`, `loop_cpu;dur`를 덧붙인다. 기존 필드의 이름·순서는 바꾸지 않는다. 뜻은 위 표와 같고 응답 header를
보내는 시점까지의 값이다(본문 전송 시간은 빠진다).

내부 계측이므로 익명 호출자에게는 보내지 않는다. 12301은 `/health`·공개 조회·일반철도·MCP location에서,
12307은 server 전체에서 `proxy_hide_header Server-Timing`으로 뺀다. 남는 곳은 allowlist가 있는 12301 export
location(Map)과 backend 직접(loopback 12302, 관리 BFF·측정 스크립트)이다.

## 공개 gateway 가드레일

- 공개 장소 조회의 `limit`은 두 gateway에서 900을 넘지 않는다(MUI-08). 12301 `location = /v1/transport/features/places`와
  12307 `location = /v1/transport/fuel/places`가 `$arg_limit`을 판정해 upstream query **끝**에 `&limit=<값>`을 붙인다
  (Starlette는 반복 query의 마지막 값을 쓴다).
  - 생략 → 900. backend 기본 1000이 상한을 넘으므로 gateway가 값을 정한다.
  - 1~900 → 그대로. 900 초과 정수 → 900(응답 `truncated`로 확인).
  - 그 밖(0·부호·앞자리 0·소수·인코딩 숫자·문자) → 422 problem+json. backend가 같은 종류의 query 검증 오류에 쓰는
    상태·다섯 항목(`type`·`title`·`status`·`detail`·`instance`, ADR-005)과 같고, `instance`는 클라이언트가 부른 경로다.
  - 관리 지도(최대 900)·공개 유가(300)는 영향이 없다. 관리 목록 검색(최대 5000)은 관리 BFF가 backend 12302를 직접
    부르므로 gateway를 지나지 않는다. backend 자체 상한(5000)과 OpenAPI의 `limit` 설명에 같은 내용을 적었다.
  - backend의 다른 오류(지금의 422·503, places admission의 429·504)는 gateway가 바꾸지 않고 그대로 전달한다.
  - `scripts/benchmark-db-reads.py`·`scripts/observe-read-baseline.py`의 `limit=5000` 표본은 backend 직접(12302)으로
    잰다. gateway를 가리키면 900으로 낮춰져 결과가 조용히 작아진다(observe는 12301·12307에 대형 지도 표본을
    요청하면 거절한다).
- export location(12301)은 `proxy_buffers 64 32k`(요청당 최대 2MiB)와 `proxy_max_temp_file_size 0`이다.
  - 주유소 500행 페이지(약 1.2MB 비압축)는 메모리 버퍼에 다 들어가 backend 연결을 바로 돌려준다. backend는
    gzip을 받는 요청(Map httpx 기본)에 T1을 gzip으로 보내므로(ADR-013 개정 2026-11-24) 실제 페이지는 더 작다.
    컨테이너 쓰기 계층의 `proxy_temp` 파일에 쓰지 않으므로 기존 `an upstream response is buffered to a temporary file`
    경고가 없어야 한다.
  - 버퍼보다 큰 본문(대형 참조 snapshot)은 소비자가 읽는 속도로 흘리며, 그동안 backend 연결과 요청을 잡고 있다.
    소비자가 `send_timeout`(기본 60초) 동안 읽지 않으면 nginx가 끊는다.
  - `limit_conn transport_export 6`으로 동시 export를 6개로 묶어 버퍼 합을 12MiB 이하로 둔다(64MiB gateway를 공개
    API·MCP와 공유). 넘으면 gateway가 `503` + `Retry-After: 10` problem+json(export 503 사유 `code`=`EXPORT_BUSY`,
    [handoff](../map-service-exports-handoff.md))으로 거절한다(`uct=-`). Map은 dataset
    페이지를 순차 조회하므로 평소에는 닿지 않는다.
- 공개 유가 gateway는 JSON을 gzip level 1(1KiB 이상, `gzip_proxied any`, `Vary: Accept-Encoding`)로 압축한다(MUI-11).
  - backend가 이미 gzip으로 준 가격 이력은 다시 압축하지 않는다. 압축 효과는 access log `gz`로 본다.
  - nginx gzip은 200·403·404만 압축한다. 오류 본문(problem+json)은 1KiB 미만이라 `gzip_types`에 넣지 않았다.
    HEAD는 GET과 같은 header(`Content-Encoding: gzip` 포함)를 본문 없이 돌려준다(nginx 1.27.5 실측).
  - 이 압축은 `fuel-api` 직접 호출용이다. 공개 UI BFF(`/api/public/fuel/*`)는 같은 호스트 loopback으로
    `Accept-Encoding: identity`를 보내 압축·해제 CPU를 쓰지 않는다(그 요청은 `127.0.0.1`, `gz=-`).
    브라우저↔Next 구간의 압축 여부는 Next 실행 설정이 정하며 이 변경 범위 밖이다.
- IP별 `limit_req`·`limit_conn`은 공개 경로에 두지 않는다. 공개 유가 사용자는 모바일 통신사 NAT 뒤에서 같은 주소를
  공유하므로 주소별 제한은 정상 사용자를 막는다. 무거운 요청은 위 `limit` 상한과 backend places 검증의
  `CapacityLimiter(2)`(`fuel_map_limiter`)로 묶는다. export의 `limit_conn`은 주소별이 아니라 listener 전체 한 key다.
