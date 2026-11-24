# Map 호출 속도·실패 방지 종합 검토 — 2026-11-24

소유자 요청: 최신 코드 기준으로 map 호출의 속도 개선과 실패 방지 방안을 검토해 단일 문서로 정리한다. 특히 다음을 확인한다.
(1) 트랜잭션 단위가 커서 메모리·lock 문제가 있는가, (2) 초기 1회가 느린 부분을 prewarm이나 배포 시 신규 코드로 줄일 수 있는가,
(3) 그 밖의 문제.

- 기준: Transport `main` 38814d8(조사), abe195a(문서 작성 시 재확인). Map `origin/main` 5d6ebf541.
- 방법: 7개 영역(T1 export, T2/T3 고정 snapshot export, T4 가격 이력, 지도 UI 읽기, 런타임·배포, Map 소비자, 쓰기 경합·실패 이력)을 각각
  조사했다. 영역마다 독립 반박 검증을 거쳤고, 완결성 비평에서 나온 공백 3건(유가 503 사건, 운영 지연 기준선, 호스트 경합)을
  추가로 조사했다. 에이전트 18개를 썼고, 발견 약 110건 가운데 반박 검증에서 정정된 문장은 정정본만 실었다.
- 제약: 코드와 문서를 읽기만 했다. 운영 접근은 공개 GET 2회(`/health`, `/v1/transport/collector-status`)뿐이다. 운영 DB·컨테이너에는
  접근하지 않았다. 그래서 **운영 지연 수치는 새로 재지 않았다.** 아래 수치는 모두 출처(문서·측정 환경)를 함께 적는다.
- 용어: 이 문서에서 "map 호출"은 (a) kor-travel-map이 `/v1/service/exports/*`를 부르는 서버 간 호출(T1~T4)과
  (b) 지도 UI(관리 `/map`·`/fuel`, 공개 유가 지도)가 `/v1/transport/features/places` 등을 부르는 호출을 함께 가리킨다.

## 0. 결론 먼저

| 질문 | 답 |
| --- | --- |
| 트랜잭션이 커서 **Map export·지도 읽기**가 메모리·lock 문제를 겪는가 | **아니다.** 읽기 경로는 페이지(요청) 단위 읽기 전용 트랜잭션이고 AccessShareLock만 잡는다. 행 잠금이 없어 수집기의 긴 쓰기 트랜잭션에 막히지 않는다. 남은 약점은 크기가 아니라 **보유 시간**이다. T1은 응답 송신이 끝날 때까지 RR snapshot과 풀 연결을 쥐고, `statement_timeout` 120초가 Map read 30초보다 길어 Map이 포기한 작업이 계속 돈다. |
| 그렇다면 큰 트랜잭션·메모리 문제는 어디에 있나 | **쓰기(수집기)와 API 프로세스 동거**에 있다. 고속도로 소통 저장 한 트랜잭션이 운영에서 175초 이상(Map 감사 4분 이상) 걸린다. 공항 수집마다 API 프로세스(512MiB, swap 0) 안에서 30일 주차 이력 약 52만 행을 다시 만든다(회당 84~122초 wall, 운영 RSS 표본 405MB). lock 장애는 writer끼리 났고(상태 행 55P03 38건), 0048로 해소했다. 같은 형태의 counter 행 잠금은 다른 10개 표에 잠복해 있다. |
| 초기 1회가 느린 이유 | 세 가지가 겹친다. ① 기준정보(T3) artifact의 입력 revision에 `release_sha`가 들어 있어 **배포마다 전부 무효**가 된다. 미리 만드는 작업은 code-server 냉기동과 다음 공항 run 뒤에야 돈다. ② API 기동 직후 **주차 이력 전체 재구성**이 첫 요청과 CPU·GIL을 다툰다. ③ 입력 지문 memo(rail만 warm)·풀·프로세스 캐시가 비어 있다. PostgreSQL은 Transport 배포 때 재시작하지 않으므로 `pg_prewarm`은 이 문제에 거의 기여하지 않는다. |
| prewarm·배포 시 신규 코드로 줄일 수 있나 | **가능하다. 배포 직후 단계를 추가하는 것이 가장 싸다.** 새 code-server 컨테이너 안에서 기존 `prepare_reference_exports_for_settings`를 1회 실행하고, backend 컨테이너 안에서 loopback smoke 겸 warm을 돌린다. 이와 함께 기동 warm을 rail·ferry로 넓히고, 풀을 미리 채우고, 이력 재구성을 그 뒤로 미루며, 준비 op를 종류별로 격리하고 오프라인 예산을 쓴다. 근본 해법은 artifact identity를 `release_sha`가 아닌 **코드 지문**으로 바꾸는 것이다(후속, §4.3). |
| 실제로 난 실패 | ① **T1 `fuel-stations` 503**: 11-23 08:17Z~11-24 00:17Z, 약 16.6시간. 유가 수집 3연속 실패로 24시간 유예를 넘겼다. 수정(#258·#261)은 운영 release 1da1862에 들어 있고 00:54Z에 회복했다. 다만 여러 run에 걸친 수용은 미완이다. ② **돌발 활성 집합 503**: 14일 80~83회. 마지막 시도 1회만 실패해도 즉시 503을 낸다. ③ 11-17 **디스크 가득 → PG PANIC**: 원본 이력 표에 보존 정책이 없다. |
| 실패를 없애는 방향 | 첫째, **503의 의미를 기계가 읽게** 만든다(`code` + `Retry-After`). 그러면 Map이 몇 시간짜리 stale을 30·90초 뒤에 헛재시도하지 않는다. 둘째, timeout 예산을 소비자보다 짧게 정렬한다. 셋째, 일시 DB 오류를 구분한다. 넷째, 유가 신선도 경보와 '실행 소실' 기록을 둔다. 다섯째, 정책 사항은 소유자가 결정한다(§9): 돌발 유예, T1 stale을 200으로 낼지, 원본 보존. |
| 가장 큰 속도 개선 | ① Map이 **매시 주유소 24페이지를 전량 재수집**하는데 원천은 8시간마다만 바뀐다(약 87% 중복). 소비자에서 생략하거나 ETag/304를 쓴다. ② T1에 gzip·thread offload·조기 연결 반납을 넣는다. ③ 공개 유가 지도의 places에 admission·deadline·single-flight를 넣는다. ④ 이력 재구성을 증분화하거나 프로세스 밖으로 옮긴다. |

이 문서와 함께 10개 개선 PR을 병렬로 진행한다(§8). 소유자 결정이 필요한 항목은 §9에 모았다.

## 1. 호출 경로와 공유 자원

### 1.1 누가 무엇을 얼마나 부르나

| 소비자 | 경로 | 주기·크기 | 비고 |
| --- | --- | --- | --- |
| Map Valkey 상태 job(n150 Dagster) | T1 `fuel-stations` | `17 * * * *`(매시). 11,885곳을 limit 500으로 읽어 **24~25페이지** | 원천(오피넷)은 `0 */8 * * *`(00·08·16시 KST)에만 바뀐다 |
| 〃 | T1 `rest-area-fuel-prices` | `27 * * * *`, 보통 1페이지 | 원천은 4시간 주기(`25 */4`) |
| 〃 | T1 `highway-incidents/active` | `3-59/10 * * * *`, 전체 집합 167~351건 | 503이면 step 재시도 30초→90초 |
| 〃 | T1 `rest-areas`, `airports` | 하루 1회 | `airports`는 요청마다 KrairportClient를 만든다(§7) |
| Map PG feature 적재(주간) | T3 `rail-stations`, `ferry-ports` | 월 04:30/04:40 KST, limit 500. rail 1,466건이라 3페이지 | 주유소 PG 적재 schedule은 운영에서 **한 번도 켜지지 않았다**(10-12 이후 6주 stale, Map 소유) |
| Map API(동기, 사용자 요청 안) | T4 `price-history` | read 5초 | **기본 꺼짐**, 운영 활성화 미완. 위험은 잠재 상태다 |
| (미사용) | T2 `highway-traffic/current`, `parking/current`, T3 `bus-terminals` | — | Map `origin/main` 코드에서 호출 0건. 그래도 Transport는 5분마다 parking artifact를 만든다 |
| 공개 유가 지도 | fuel-web BFF → fuel gateway :12307(30초) → `features/places?kind=fuel_station` | 팬·줌마다 | 항상 `include_fuel_statistics=true`라 page cache를 타지 않는다 |
| 관리 `/map`·`/fuel` | admin BFF → backend 직접 | 팬·줌마다 | admin BFF는 브라우저 abort를 upstream에 전달하지 않는다 |
| 관리 고속도로 | `/transport/highways/*`, ITS Chromium(`/roads`, `/road-traffic`) | 화면 진입 | 한 번 실패하면 15분 동안 429 |

호출 경로는 n150 Map → odroid API gateway :12301(nginx, CIDR allowlist, `proxy_read_timeout 120s`) → backend :12302다.
ADR-013 근거 절의 "같은 호스트 loopback" 설명은 2026-10-14 이후 운영과 다르다. 실제 접근 경계는 gateway CIDR이고,
거부되면 404가 아니라 403이다(T1-13).

### 1.2 모두가 나눠 쓰는 것

- **API 프로세스 하나**: uvicorn에 `--workers`가 없다. `mem_limit`=`memswap_limit`=512m. 장비는 ODROID M1S(Cortex-A55 4코어, RAM 7.6GiB, swap 0)다.
  T1~T4, 공개·관리 지도, 주차 화면, `/health`, 주차 이력 재구성 thread, ITS Chromium 자식 프로세스가 모두 이 안에서 돈다.
- **DB 풀 하나**: `pool_size` 5 + `max_overflow` 5 = 10. `pool_timeout`은 기본 30초다. 풀 대기가 timeout되면 500이 된다.
- **호스트 경합은 상시다**: load 20~28, 하루 약 1,000 Dagster run, run worker 기동 p50 30초. weather 단기예보 듀티가 약 76%다.
  weather code-server는 `cpu_shares` 4096인데 Transport API는 기본 1024다.
  [추론] 분 단위로 시간대를 옮겨도 조용한 창이 거의 없다.

### 1.3 timeout 예산(현재)

| 구간 | 값 | 문제 |
| --- | --- | --- |
| Map → export | connect 4초, read 30초. HTTP 재시도는 전송 오류·502/504에만 15초 뒤 1회. 그 밖은 step 재시도(상태 job 30·90초, PG 적재 60·120·240초) | 500·408·429는 HTTP 층에서 재시도하지 않는다. 503은 사유와 무관하게 같은 재시도를 탄다 |
| export gateway | `proxy_read_timeout` 120초 | Map 30초보다 길다 |
| API 엔진 | `statement_timeout` 120초. lock_timeout·connect timeout 없음(asyncpg 기본 connect 60초) | Map이 30초에 끊어도 서버 작업은 최대 120초 계속된다(G3-08, RT-04) |
| T2/T3 snapshot 트랜잭션 | RR, `lock_timeout` 2초, `statement_timeout` 10초, 본문 구성 예산 15초 | **T1·T4에는 이 상한이 없다**(감사 중 바로잡은 일반화, 부록 A) |
| 공개·관리 gateway | 30초 | places에 deadline이 없어 504 뒤에도 문장이 계속 돈다 |
| T4 | Map 5초. PinVi → Map도 5초 | timeout 역전으로 PinVi의 공용 'transport' 회로가 열릴 수 있다(T4-05, 잠재) |

## 2. 질문 1 — 트랜잭션 크기, 메모리, lock

### 2.1 읽기 경로(Map export·지도 UI)

| 경로 | 트랜잭션 범위 | lock | 메모리 | 판정 |
| --- | --- | --- | --- | --- |
| T1 페이지 | 페이지당 RR 1개, 문장 3~4개(state, keyset 본문, 최신가 IN, 주소 IN). FastAPI request-scope yield 의존성 때문에 **응답 송신이 끝나야** 닫힌다 | AccessShareLock만. 행·advisory lock 없음 | 500행 기준 pydantic+본문 약 6.6MB(합성 측정). ORM 엔터티(유가 약 2,500개/페이지)는 별도 | 크기 문제는 없다. 보유 시간과 timeout 부재가 문제다(T1-04, RT-08) |
| T2/T3 첫 페이지(미준비) | RR 하나 안에서 지문 → 전체 본문 구성 → 400행 COPY → head CAS → 만료 handle 1개·미사용 artifact 1개 GC → handle INSERT → 페이지 SELECT | unique admission 대기 2초 넘으면 55P03 → 503. 40001은 1회 재시도 | canonical bytes 전체(rail 1.43MB, 상한 16MiB/20,000건) | 쓰기를 하는 읽기 API다. 준비된 artifact가 있으면 handle 쓰기만 남는다 |
| T4 | 작은 인덱스 조회, 응답 전에 rollback | AccessShareLock | 작음 | 문제없음. 다만 주유소 조회가 인덱스 없는 `source_station_id`로 걸린다(T4-01) |
| places | 요청 세션 하나, 읽기 전용(page cache 증명 경로만 RR) | AccessShareLock | 5,000곳 유가 지도 격리 peak 196MB | 유가 상세는 limiter(2)를 **기다리는 동안 풀 연결을 쥔다**(MUI-02, P1) |

결론: 읽기 쪽 "트랜잭션이 커서 lock이 걸리는" 경로는 현재 코드에 없다. export 읽기가 writer lock에 막힌 사례도
문서에서 찾지 못했다(WLH-13, G3-11). 남은 것은 다음 세 가지다.

1. T1·T4·places에 경로별 `statement_timeout`·`lock_timeout`·전체 deadline이 없다.
2. T1이 구성·직렬화·송신 동안 연결을 쥔다.
3. T2/T3 첫 페이지가 epoch(15분)마다 쓰기를 한다. 이 때문에 동시 첫 요청이 경합하고, 준비 op와도 겹친다(T23-01, WLH-12, 발생 기록 없음, P3).

### 2.2 쓰기 경로(수집기)

| 항목 | 내용 | 근거·상태 |
| --- | --- | --- |
| 고속도로 소통 저장 | 한 트랜잭션에서 원본 약 8,300행, current upsert, 최근 2시간 5분 통계 재구축, 상태 갱신을 모두 한다. **운영 175초 이상, Map 감사 4분 이상**. 격리 저장은 1초 미만이라 대부분 통계 재구축·I/O 경합으로 추정한다. 센서가 멈춘 구간의 과거 bucket을 매 run 다시 집계하고, 반복 관측 행의 raw JSON을 매번 UPDATE한다 | WLH-06(P2 확인), 누락 보고. 5분 주기의 60~80% 동안 xid를 쥐어 vacuum horizon을 고정한다 |
| 유가 저장 | 주유소 약 1.2만 곳 + 가격 약 5.5~5.9만 행 upsert를 한 트랜잭션에 한다. n150 기준 69~93초 | 집합 upsert(호출 142,621→59)로 개선했다. MVCC라 export를 막지 않는다 |
| 공항 run 안의 네트워크 I/O | 주차 current 승격과 같은 트랜잭션에서 인천 요금 HTTP(최대 15초)를 호출한다. 그동안 새 current가 보이지 않고 revision 행 잠금이 유지된다 | WLH-08(P3). 요금 fetch 예외가 주차 저장을 rollback하지는 않는다 |
| advisory lease 연결 | `pg_try_advisory_lock` 뒤 commit이 없어 run 내내 `idle in transaction`이다 | **서버 `idle_in_transaction_session_timeout`·`transaction_timeout`을 그대로 넣으면 공항 run이 5분마다 실패한다**(검증 결과). lease 직후 commit을 먼저 넣어야 한다 |
| 문장 trigger counter 행 | 0045/0046 10개 표(유가·주유소·공항·돌발 등)와 0043 기준정보 표는 쓰기 트랜잭션이 counter 행을 commit까지 잠근다 | 상태 표 38건은 0048로 해소했다. 나머지 표는 두 번째 writer(관리자 좌표 보정, KRIC 매핑)가 겹칠 때 관리자 요청이 lock_timeout 없이 기다리는 잠복 위험이다(P3) |
| 진단 장치 | `application_name`, `log_lock_waits`가 없다 | 38건 lock timeout의 원인을 코드 추론으로만 찾았다(WLH-09) |

### 2.3 메모리

- API 컨테이너 512MiB(swap 0) 안에 다음이 함께 들어 있다.
  - 이력 캐시 상주분과 재구성 peak(옛 snapshot, 52만 개 NamedTuple, 새 snapshot, 75MB 렌더, br q6·gzip 9 압축본이 잠시 공존한다).
  - 5,000곳 유가 지도.
  - ITS Chromium.
- 측정값의 성격:
  - **운영 표본은 RSS 405MB 1회뿐이다**(여유 약 100MB).
  - 475~498MiB는 x86·1,536MiB 한도에서 합성 50만 행으로 잰 별도 프로세스 값이다. 512MiB 근접의 근거로 쓰지 않는다(MUI-03 정정).
  - OOMKilled·재시작 기록은 문서에 없다.
- ADR-014의 설계 예산은 backend 0.8g이다. n150 실측은 0.55GiB(≈563MiB)로 지금 한도보다 크다.
- 조치:
  - 운영 `docker inspect`(OOMKilled, RestartCount)와 cgroup `memory.max_usage_in_bytes`·`failcnt`를 먼저 확인한다.
  - 이력 재구성은 증분화하거나 프로세스 밖으로 옮긴다(RT-01, G3-02).
  - 그 전까지 `--workers` 증설은 금지한다. 재구성과 메모리가 워커 수만큼 늘어난다.

## 3. 실패 원장 — 지도 호출과 관련된 실제 사건

| 사건 | 규모 | 직접 원인 | 상태 |
| --- | --- | --- | --- |
| T1 `fuel-stations` 매시 503 | 11-23 08:17Z~11-24 00:17Z, Map run 약 17건 실패(추론) | 오피넷 수집 3연속 실패(CDP `Invalid InterceptionId`, 상태 claim 55P03) → `last_success_at`+24h 초과 | 수정 #258·#261이 운영 1da1862에 포함됐고 00:54Z에 성공했다. **수용은 미완**: 정기 run 9회 무실패 확인, 22:56Z 회복 run의 출처 확인(G1-F1) |
| 돌발 활성 집합 503 | 14일 80~83회. 0건 200 응답 37회는 #265 뒤 503으로 바뀜 | 마지막 시도 1회 실패(`last_error`)만으로 즉시 503. 30분 초과 장기 정지도 섞여 있다 | 정책상 의도(ADR-013 2026-10-23 "돌발은 바꾸지 않는다") → **소유자 결정**(§9) |
| 11-17 디스크 가득 → PG PANIC | 공용 NVMe 여유 1.9GB | 원본 이력 표(고속도로 소통 raw 약 240만 행/일 추정, 유가 가격 raw 중복)에 보존 정책 없음 | **미해결, P1**(WLH-02). 보존 기한은 소유자 결정 |
| 상태 행 lock timeout | 55P03 38건(공항 26·휴게소 유가 10·유가 2) | 0045 문장 trigger가 상태 행 쓰기를 직렬화 | 0048(#261)로 해소. 운영 로그 0건 확인이 남았다 |
| 공개 places zoom 7 504 | 30초 504 3/3 | 새 공개 세대를 계획기가 1행으로 추정 | #247(`fixed_generation`, 0047)로 해결 |
| 유가 저장 14~16분·MV refresh 60초 초과·3일 통계 504 | — | — | 집합 upsert, 0022 증분 upsert, 5분 사전 집계로 해결 |
| T3 첫 요청 cold | 12.43초 / 18.73초(상태 코드 미기록) / 3.24초 / 7.57초 / 10.83초(문맥 불명확) | 배포마다 artifact 무효 + 요청 안 구성 + 이력 재구성 경합 | 부분 해결(COPY, 준비 op, rail warm). 이번 §8 C로 보강 |

실패 비중의 분모에 주의해야 한다. Map 감사의 "Map 실패 57%가 상류 신호"는 Map 테넌트 실패 380건 기준이다.
n150 전체 실패 2,314건 기준으로는 상류 stale이 6.6%이고, 81.6%는 code-server fd 고갈(launch 실패, Map 쪽 문제)이다.
14일 동안 Transport 상태 job의 상류 신호 실패는 약 131건(돌발 503 80, 0건 거부 33, 주유소 503 18)이다.

## 4. 질문 2 — 초기 1회 느림과 prewarm

### 4.1 원인 분해

| 원인 | 영향 범위 | 근거 | 크기 |
| --- | --- | --- | --- |
| `release_sha`가 T3 입력 revision namespace에 들어간다(`reference_export_revision.py`, `export_references.py:385`) | 배포마다 rail·ferry·bus·parking artifact 전부 무효. 다음 공항 run 준비 step 전까지 첫 페이지가 요청 안에서 구성한다 | T23-03, WLH-03, RT-03, MC-07 | 배포 직후 rail 7.574초 기록. Map은 월요일 04:30 직전 배포일 때만 만난다(P3) |
| 기동 직후 주차 이력 전체 재구성 | 같은 프로세스의 모든 첫 요청 | RT-01, G2-02, G3-10 | 회당 84~122초 wall. 재기동 직후 cold 표본은 항상 이 재구성과 겹친다 |
| 입력 지문 memo가 프로세스 메모리(LRU 64)에만 있다 | rail만 기동 시 warm. Map의 주 1회 호출은 거의 항상 miss(heads가 매일 바뀜) | T23-02 | ARM 기준 지문 약 0.7~1.1초 |
| 풀·연결 준비 상태 | 새 연결마다 TCP·SCRAM·코덱 설정·카탈로그 비용이 든다. overflow 연결은 반환하면 바로 닫힌다 | RT-13 | 연결당 수십 ms(추론) |
| 프로세스 캐시 | places page·검증 LRU, viewport·시군구·중심 캐시, ITS 카탈로그 | MUI-05, MUI-07 | ITS는 cold 한 번 실패로 15분 차단 |
| 앱 bytecode 없음 | 기동마다 앱 소스 약 1.4MB 컴파일. playwright 즉시 import | RT-14 | x86 0.16~0.19초. A55는 수 배(추론) |

PG 버퍼는 원인이 아니다. Transport 배포는 공용 PostgreSQL을 재시작하지 않는다. 공용 PG 설정(n150 시절 128MB 기록 대
odroid PG18.6 768MB 보고, Manager autoprewarm 여부)은 문서끼리 어긋나므로 운영에서 확인해야 한다.

### 4.2 prewarm·배포 시 신규 코드 — 평가

| 방안 | 위치 | 효과 | 위험·조건 | 판정 |
| --- | --- | --- | --- | --- |
| 배포 직후 T3 artifact 준비 | 배포 경로. 새 `dagster-code-server` 컨테이너 안에서 `prepare_reference_exports_for_settings`를 timeout을 걸고 best-effort로 1회 실행 | 배포 직후 cold 창 제거 | Dagster `launchRun`은 `reference` run_group 동시 1개와 odroid 대기열(p95 10~50분) 때문에 늦다 → 컨테이너 직접 실행이 낫다. 실패해도 배포는 실패시키지 않는다 | **채택**(§8 C) |
| 배포 직후 loopback smoke 겸 warm | backend 컨테이너 안에서 `python -I -m <모듈>`. 토큰은 컨테이너 env에서 읽고, T1 `limit=1` 5종과 rail·ferry 첫 페이지를 부른다 | 서빙 프로세스를 데우는 유일한 수단이고, 토큰·allowlist·flag 불일치를 배포 시점에 잡는다 | 토큰을 argv나 로그에 남기지 않는다. 404·503은 경고로만 처리한다 | **채택**(§8 C) |
| 기동 warm 확장 | API lifespan, yield 뒤 task | rail에 더해 ferry 지문. 풀 채우기(SELECT 1×pool_size, 3초) | bus·parking은 Map이 쓰지 않는다. memo는 heads 변경으로 곧 무효다. yield **전에** 하면 포트 개방이 늦어져 502 창이 늘어난다 | **부분 채택**(§8 C) |
| 이력 재구성 시작 후순위 | lifespan | 기동 직후 CPU·GIL 경합 완화 | 지연 동안 `/parking/history` 전체 요청이 무거운 직접 SQL로 간다. 짧게(warm 완료나 최대 30초) 미룬다 | **조건부 채택**(§8 C·G) |
| readiness gating | `/health` | — | 단일 인스턴스·고정 포트라 트래픽을 막지 못한다. healthcheck에 걸면 Manager adopt를 막는다 | 기각(관측 로그만) |
| `pg_prewarm`/autoprewarm | 공용 PG(Manager) | PG 재시작 직후에만 효과 | 공용 인스턴스 재시작과 권한이 필요하다 | 이 목적에는 기각. Manager 백로그로 별도 |
| artifact identity를 코드 지문으로 | `reference_export_revision.py` | 무관한 배포에서 artifact 생존. API·code-server `release_sha` skew 때 head가 5분마다 왕복하는 문제 해소 | 사람이 올리는 버전 상수는 빠뜨리기 쉽다. import 시 builder·주소 투영·schema 소스 hash와 page model JSON schema, kortravelcommon·krairport 버전으로 자동 계산해야 한다. ADR-016 개정이 필요하다 | **후속**(설계는 §4.3) |
| 입력 지문 DB memo | 작은 memo 표 또는 heads 열 | 준비 op의 5분×4종 재계산과 Map 첫 페이지 약 1초 제거 | 정합성 전제는 지금 memo와 같다(0043 trigger가 모든 writer를 포괄) | 후속 |
| 준비 op의 handle 사전 생성·GC 이관 | Dagster 준비 op | 요청 경로의 GC·admission 경합 감소 | handle 조회 key가 지문에서 나오므로 사전 생성은 DB memo와 함께여야 의미가 있다 | GC 이관은 채택(§8 C), handle 사전 생성은 후속 |
| T1 revision 키 페이지 캐시 | API 프로세스 | 매시 24페이지 재구성 제거(효과 최대) | 주소 admin 변경 반영과 envelope 생성 규칙이 필요하다. 소비자 생략(§5.2)이 더 싸다 | 후속(Map 쌍) |
| ITS 카탈로그 기동 warm | lifespan | 첫 관리자 방문 | 지금 구조에서는 warm이 한 번 실패하면 15분 차단된다. 차단 상태 분리가 먼저다. Dagster에 저장하는 방식이 낫다 | 후속 |
| Map T3 적재 전 warm probe | Map | — | 생산자 예산(15초) 안이라 이득이 작다 | 기각 |

### 4.3 artifact identity 후속 설계(요지)

`input_revision` namespace의 `release_sha`를 `payload_code_fingerprint`로 바꾼다. 이 값은 import 시점에 다음을 해시해 계산한다.

- payload builder 4종의 모듈 소스
- `export_admin_addresses`
- 페이지 모델 JSON schema
- `kortravelcommon`·`krairport` 배포 버전

읽을 때 `page_model` 재검증은 그대로 유지한다. 코드 지문이 바뀌었는데 artifact가 재사용되는지 확인하는 계약 시험을 둔다.
도입 전까지는 배포 검증에 "code-server `RELEASE_SHA` = API `release_sha`" 확인을 넣는다. code-server만 롤백되는 경로에서
head가 서로를 덮어쓰기 때문이다.

### 4.4 운영 기준선이 없다

현재 main 이미지에서 Map 호출 지연을 잰 기록이 없다. T3 cold 수치 다섯 개는 이미지와 환경이 각기 다르고,
로컬에서 31.68% 줄인 COPY 뒤에 운영 값은 오히려 늘었다. 표본이 코드보다 환경에 좌우된다는 뜻이다.
T1과 T4는 운영 실측이 0이다. 1초 미만 요청은 로그에 남지 않는다.
측정 절차와 계측 보강(§8 E)을 함께 진행한다.

1. **A**: `/health` `release_sha`와 backend `StartedAt`을 기록한다.
2. **B**: `docker logs --since <StartedAt>`에서 `slow_request`·`parking_history_rebuild`·warmup 로그를 route×status×duration으로 집계한다.
   시작 시각은 종료 시각에서 duration을 빼서 구하고, 재구성 구간과 겹치는지 표시한다.
3. **C**: Map n150 Dagster에서 `transport_state_*`·`feature_place_transport_*`의 14일 step 소요를 뽑는다.
4. **D**: 공항 job `prepare_reference_exports` step 소요를 잰다.
5. **E**: 다음 배포 때 통제된 첫 요청(사전 warm 없음)을 1회 잰다.
   판정에는 재구성 구간 밖의 표본만 쓰고, 측정 기록에 `release_sha`·loadavg·동시 run 수를 남긴다.

## 5. 질문 3 — 실패가 나지 않게

### 5.1 503의 의미를 기계가 읽게(생산자·소비자 쌍)

지금은 몇 시간짜리 stale과 수 초짜리 snapshot 경합이 사유 코드도 `Retry-After`도 없는 같은 503이다. Map은 둘 다
`TransportExportNotCurrent`로 받아 30·90초 뒤에 step을 처음부터 다시 돈다. 이 재시도는 데이터를 하나도 바꾸지 못하고
빨간 run과 중복 부하만 남긴다. 실패한 시도는 저장을 rollback하므로 마지막 성공 집합은 그대로다.
계약은 problem+json에 가산 필드 `code`와 `Retry-After` 헤더를 더하는 방식이다. `code`가 없으면 지금과 같은 의미다.

| code | 조건 | Retry-After |
| --- | --- | --- |
| `EXPORT_SOURCE_NOT_CURRENT` | T1 참조 집합 stale·유예 초과 실패 | `next_due_at`까지 + 예상 수행시간(60~28,800초), 모르면 1,800 |
| `EXPORT_NO_HISTORY` | 원천 성공 이력 없음 | 3,600 |
| `EXPORT_INCIDENTS_NOT_CURRENT` | 돌발 활성 집합 last_error·나이 초과 | 300 |
| `EXPORT_EMPTY_SET` | 돌발 0건 집합(#265 정책) | 300 |
| `EXPORT_BUSY` | snapshot admission 경합(55P03, 반복 40001) | 10 |
| `EXPORT_PREPARE_TIMEOUT` | 본문 구성 예산 초과, snapshot 작업 중 57014 | 60 |
| `TRANSIENT_DB` | 풀 대기 초과, 접속 실패, 57P03, 53300 | 15 |

소비자(Map)는 이렇게 처리한다.

- `SOURCE_NOT_CURRENT`·`NO_HISTORY`(또는 `Retry-After`가 남은 재시도 창보다 긴 경우): 재시도하지 않는다. 직전 세대를 유지하고 사유 metadata를 남긴다.
- `BUSY`·`PREPARE_TIMEOUT`·`TRANSIENT_DB`: 같은 cursor로 `Retry-After`를 존중해 페이지 단위로 재시도한다(최대 60초, run 예산 공유).

이 밖에도 정리할 것이 있다.

- T2/T3 snapshot 작업 중의 57014는 지금 사유 없는 500이다. 503 `EXPORT_PREPARE_TIMEOUT`으로 바꾼다.
- admission 55P03은 0.3~1초 jitter를 두고 새 RR로 1회 재시도한 뒤 503을 낸다. RR 안에서 advisory lock으로 single-flight를 하는 안은 snapshot 시점 때문에 안전하지 않아 기각했다.

### 5.2 timeout 예산 정렬

- T1: `SET LOCAL statement_timeout '20s'`, `lock_timeout '3s'`, READ ONLY. 마지막 SQL 뒤 연결을 반납한다.
- places: 전체 deadline 약 25초(gateway 30초 미만), 문장 상한, admission·single-flight.
- T4: 문장 상한 약 5초(Map T4 예산).
- API 엔진: connect timeout 10초, `pool_timeout` 10초를 명시한다. `application_name`으로 API와 수집기를 구분한다.
  API 엔진의 `lock_timeout`은 쓰기 경로를 조사한 뒤에만 넣는다.
  **수집기 엔진에는 `idle_in_transaction_session_timeout`·`transaction_timeout`을 지금 넣지 않는다**(lease 연결, §2.2).
- Map 쪽에는 요청 전체 deadline이 없다. `ReadTimeout` 뒤 15초 만에 같은 요청을 다시 보내 서버 작업이 겹친다.
  step 재시도 때 마지막 성공 cursor부터 이어 읽는다(T1 cursor는 정수 id라 멱등이다).

### 5.3 유가 신선도(이번 503 사건의 재발 방지)

- **틈 (1) 닫기**: export 전용 오피넷 유예를 `FUEL_STALE_AFTER`에 유가 run fetch timeout을 더한 값으로 늘린다.
  ADR-013에 기록된 틈 (1)은 연속 2회 실패 뒤 세 번째 run이 조금만 늦어도 503이 되는 틈이다. 공개 화면 기준은 그대로 둔다.
- **실행 소실**: run이 op 밖(worker 소실, SIGKILL)에서 죽으면 `last_error`가 남지 않는다. 이때 관리자 '재시도'가
  '호출 유예'로 건너뛰어진다. 회수 시점에 '실행 소실'을 기록한다(G1-F5).
- **경보**: 지금 정체 경보는 5분 수집만 본다. 유가·휴게소 유가에 '2주기 초과 + 마지막 시도 실패'(경고)와
  'export 기준의 80%'(위험) 이벤트를 둔다(G1-F6). 이번 16.6시간 503도 경보 없이 지나갔다.
- **수용**: 11-24 07:00Z부터 정기 run 9회(15:00Z 3회 포함)에서 다음을 확인한다.
  - `OPINET_BROWSER_RESOURCE_POLICY` 0건
  - lock timeout 0건
  - 재시도 run이 체크포인트에서 재개되는지
- 유가 실패는 15:00Z(00:00 KST) run에 몰려 있다(14회 중 8회). 원인은 미규명이다.

### 5.4 일시 오류와 풀 격리

- 풀 대기 초과·접속 실패·PG 기동 중은 지금 모두 범용 500이다. 503 `TRANSIENT_DB` + `Retry-After`로 구분한다.
  이로써 바뀌는 것은 운영 진단과 소비자의 재시도 방식이고, 데이터 안전성은 같다.
- export·`/health` 전용 풀 분리는 후속이다(RT-02). 그 전까지 places의 limiter 대기 중 연결 보유(MUI-02)를 먼저 없앤다.

### 5.5 디스크 고갈(가장 큰 잠재 장애)

- **보존 정책이 없는 표**: 고속도로 소통 원본(약 8,300행×288회/일)과 유가 가격 행(행마다 주유소 raw JSON 중복, 가격 null 행 약 50%)이다.
  11-17에 공용 NVMe가 가득 차 PG PANIC이 났다. 원본이 계속 늘면 3일 주기 `pg_dump`의 시간과 snapshot 보유 구간도 함께 커진다.
- **먼저 할 것**:
  1. 운영에서 `pg_total_relation_size`와 일 증가량을 읽기 전용으로 잰다.
  2. 보존 기한을 소유자가 정한다(§9).
  3. 일·월 파티셔닝으로 `DROP PARTITION`(대량 DELETE·bloat 회피)한다.
  4. 가격 행의 raw 저장을 중단한다.
  5. Manager 디스크 경보를 둔다.

## 6. 질문 4 — 속도 개선 우선순위

| 순위 | 개선 | 효과 | 비용·위험 | 상태 |
| --- | --- | --- | --- | --- |
| 1 | Map 매시 주유소 walk 생략: 첫 페이지 `last_success_at`이 Valkey 세대와 같으면 중단하고, 6시간마다 강제 전량 수집 | 주유소 페이지 요청 약 87% 감소(하루 576→약 72+α) | Map 단독, 작음 | §8 J |
| 2 | T1 gzip level 1 + `Vary`, 연결 조기 반납, 구성·직렬화 thread offload(CapacityLimiter), `airports` 정적 목록, cursor 범위 422 | 전송량 3~6배 감소(추정), event loop 차단 제거 | 출력 JSON 동일성 시험 필요 | §8 B |
| 3 | places admission·deadline·single-flight, limiter를 연결 획득 전으로 이동, LRU 예산 분리, admin BFF abort 전달 | 풀 고갈·504 뒤 잔여 작업 제거 | 중간 | §8 D |
| 4 | 이력 재구성 비용: gzip 9→6, 사전 확인 거짓 양성 제거, 재구성 중 fallback 상한, 계측 | 재구성 CPU·메모리 peak 감소 | 신선도 계약 확인 필요 | §8 G(증분화는 후속) |
| 5 | T2/T3 준비 강화(종류별 격리·오프라인 예산·GC 이관)와 배포·기동 warm | 첫 1회 cold 제거 | 작음 | §8 C |
| 6 | 고속도로 저장 트랜잭션 분리(통계 재구축을 별도 트랜잭션으로), 무변경 반복 관측의 raw 재기록 제거 | 175초 트랜잭션 축소, WAL·dead tuple 감소 | 중간, 수집 코드 | §8 F |
| 7 | T4 주유소 조회를 `identity_key` 유니크 인덱스로, 중복 조회 제거, 문장 상한 | 매 호출 전체 스캔 제거 | 작음 | §8 I |
| 8 | 공개 places 응답 캐시(공개 세대 + revision 키)나 gateway `proxy_cache`(lock·stale) | 공개 지도 반복 요청 SQL 감소 | 키 증명에 유가 통계 표 추가가 필요하다. bbox가 기기마다 달라 적중률은 제한적이다 | 후속 |
| 9 | T1 page size 1000, T3 2000 이상 | 페이지 고정비 감소 | Map 설정 | §8 J |
| 10 | 5분 job의 `in_process_executor`(run당 프로세스 2~3개 → 1개) | 하루 약 900개 Python 프로세스 기동 감소 | Dagster 실행 의미 확인 | 후속 |
| 11 | 지도 첫 화면 중복 cold 요청(기본 범위 + 실제 viewport) 제거 | 첫 방문 부하 절반 | 프런트엔드 회귀 시험 | §8 D(선택) |

## 7. 그 밖의 발견

- **ITS 도로 소통**: 프로세스 메모리 캐시뿐이고, 카탈로그와 소통이 차단 상태 하나를 공유한다. cold에서 한 번 실패하면 15분 동안 429다(MUI-07).
  카탈로그를 영속화하고, 차단 상태를 분리하고, 첫 실패에는 짧은 backoff를 둔다.
- **공개 gateway**: `limit`≤5000을 그대로 통과시키고 rate limit이 없다(MUI-08). 공개 BFF는 upstream 본문을 최대 16MB까지 모은 뒤 응답한다(MUI-14).
  UI는 `limit`≤900만 쓴다.
- **places page cache**: 무효화 범위가 전역이다(10개 표 + 상태 표 전체 digest). LRU 8개를 공개 유가 검증 항목과 공유해 관리 `/map` page를 먼저 밀어낸다(MUI-06, MUI 누락 보고).
- **관측**:
  - Server-Timing·slow log의 `cpu`는 프로세스 전체(`process_time`)라 재구성 thread CPU가 섞인다.
  - 풀 대기·limiter 대기·캐시 적중 지표가 없다.
  - gateway·uvicorn access log에 소요 시간이 없다(G2-03~06).
  - 기존 warm 장치의 성공 여부도 남지 않는다(G2-09).
- **배포**:
  - 단일 backend의 하드 재시작이다. graceful 종료 시간이 없어 기본 10초 뒤 SIGKILL된다(RT-10).
  - 검증은 `/health`와 `release_sha`만 본다(RT-11).
  - code-server만 자동 rollback되는 경로에서 `release_sha`가 섞인다.
  - Map 정시 호출(:03/:13…, :17, :27)과 배포 창이 조율되지 않는다(T1-12).
- **bytecode**: 앱 소스에 `.pyc`가 없고 `PYTHONDONTWRITEBYTECODE=1`이다. 이미지 빌드에서 `compileall --invalidation-mode unchecked-hash`를 권한다(RT-14).
- **GC pause**: 이력 snapshot의 수십만 개 상주 객체가 gen2 full collection을 유발할 수 있다. `gc.freeze()`는 누수 시험 후에만 쓴다.
- **계획 통계**: 세대 공개·정리형 표에 autovacuum·analyze 표별 설정이 없다. 문서의 정리 수치(2,000행/15초)는 코드(5,000행/60초)와 다르다(WLH-10).
- **CPU 가중치**: weather code-server는 4096이고 Transport API는 1024다. 지연에 민감한 서버를 올리는 쪽으로 Manager와 협의한다(G3-05).
- **Map 쪽**(Map 소유):
  - Valkey 적재 잠금 TTL이 `max_runtime`+660초다. 죽은 run 뒤 다음 tick이 조용히 '성공(skip)'한다(MC-13).
  - export 본문 크기 상한 리더는 dead code다(MC-14).
  - Transport가 보내는 `admin`(VWorld 법정동)을 Valkey 값에서 버린다(ADR-114 결정 6 미이행).
  - 상태 job과 생산자 수집의 schedule 위상이 겹친다.
  - T4 프록시가 요청마다 새 `AsyncClient`를 만든다(활성화 전에 고칠 점).

## 8. 이번에 병렬로 진행하는 개선 PR

각 PR은 독립 worktree에서 다음 순서로 진행한다: 구현 → Draft PR → CI → 적대적 리뷰(James·Popper) → 지적 재현·수정 → 머지.
결과(PR 번호·리뷰 반영·머지 여부)는 별도 정산 문서 PR에서 journal·resume·tasks와 함께 기록한다.

| 키 | 범위 | 주 finding |
| --- | --- | --- |
| A export-contract | 503 `code`·`Retry-After` 계약(§5.1), 57014 → 503, 55P03 1회 재시도, 일시 DB 오류 503, API 엔진 connect·pool timeout·`application_name`, 오피넷 export 유예 틈 (1) | G1-F3, MC-01, T23-10, RT-12, G1-F4(a) |
| B t1-export-perf | T1 READ ONLY + 문장·lock 상한, 연결 조기 반납, thread offload, gzip, `airports`, cursor 범위 | T1-03~09, RT-08 |
| C reference-prewarm | 준비 op 종류별 격리·오프라인 예산·GC 이관, 배포 직후 준비 + loopback smoke, 기동 warm(rail·ferry)·풀 채우기·이력 재구성 후순위 | T23-04/05, WLH-03/04, RT-06/11/13 |
| D places-admission | limiter·연결 순서, deadline, single-flight·admission, LRU 예산 분리, admin BFF abort | MUI-02, MUI-04 |
| E gateway-observability | nginx 소요 시간 log_format(`$uri`만), export 임시 파일, 공개 `limit` 상한·gzip, slow log 필드·임계값·thread CPU·풀 대기 | G2-03~06, RT-09, MUI-08 |
| F highway-store-txn | 단계별 시간, 통계 재구축 트랜잭션 분리, bucket 재집계·raw 재기록 축소 | WLH-06 |
| G history-rebuild-cost | gzip 9→6, 계측, 거짓 양성 폐기 제거, 재구성 중 fallback 상한 | RT-01, G3-02 |
| H fuel-freshness | 실행 소실 기록, 유가 신선도 경보 이벤트 | G1-F5, G1-F6 |
| I t4-history | `identity_key` 조회, 중복 조회 제거·`include_latest`, 문장 상한 | T4-01, T4-08 |
| J map-consumer(Map 저장소) | 무변경 walk 생략, 503 code·`Retry-After` 처리, 500·408·429 HTTP 재시도, page size, 요청 지연 metadata | MC-01/03/04/10, G2-07 |

배포 메모: A·B·D·E·I는 backend·gateway 배포가 필요하다. C는 배포 스크립트·code-server·backend가 필요하다.
F·H는 code-server, J는 Map 배포가 필요하다. 계약은 가산이라 생산자·소비자 배포 순서와 무관하다.

## 9. 소유자 결정이 필요한 항목

1. **돌발 활성 집합 유예**: `last_error`가 있어도 마지막 성공이 짧은 유예(예: 15~20분, Map의 30분 상한 미만) 안이면 200 +
   `last_attempt_failed`로 낼지 결정한다. ADR-013 2026-10-23의 "돌발은 바꾸지 않는다"를 개정해야 한다.
   0건 503(#265)은 유지하고 `EXPORT_EMPTY_SET`으로 구분한다.
2. **T1 참조 export의 stale을 503이 아니라 200 + `collection.stale=true`로 낼지** 결정한다. Map max_age는 48시간이라
   24~48시간 구간의 503은 데이터를 보호하지 못한다. T2/T3/T4는 이미 200 + `source_status=stale`이다.
   ADR-013 결정 3 개정과 Map 쌍 PR이 필요하다.
3. **원본 보존 기한**: 고속도로 소통 원본(예: 7~30일, 5분 집계·current는 영구), 유가 가격 행 raw JSON 정규화, 백업 제외 대상.
4. **API 메모리 한도**: 512m → ADR-014 설계 예산 0.8g 상향 여부. 운영 peak 측정 뒤 결정한다. 이력 재구성 외부화(증분 또는 Dagster 산출물)와 함께 본다.
5. **Manager 협의**: `cpu_shares` 재조정(지연 민감 서버 상향), `log_lock_waits`, 디스크 증가율 경보, `pg_prewarm`(PG 재시작 대비).
6. **Map 소유**: `feature_place_transport_fuel_stations` 주간 schedule 활성화, T4 프록시 활성화 전 timeout 재조정(PinVi 5초보다 짧게).
7. **유가 신선도 보호 재시도**: 연속 실패로 `last_success`가 16시간을 넘으면 다음 tick 전에 체크포인트 재개 run을 띄울지 결정한다(오피넷 호출 정책).

## 부록 A. 검증으로 바로잡은 주장

| 처음 주장 | 바로잡은 내용 |
| --- | --- |
| "export 읽기는 RR·lock_timeout 2초·statement_timeout 10초" | T2/T3 `_snapshot_transaction`에만 해당한다. T1(`_begin_snapshot`)과 T4는 격리 수준만 바꾸고 API 엔진 120초를 쓴다 |
| "프록시 30초보다 statement 120초가 길다"(전 경로) | export gateway는 120초다. 30초는 관리·공개 gateway다. export에서는 "Map read 30초 < gateway 120초 = statement 120초"가 맞다 |
| "재구성 중 /health p95 10배" | 11-18 측정으로, 11-19 개선(400행 yield, event loop 최대 지연 981→114ms) 이전 값이다. 현재 간섭 크기는 미측정 |
| "84~122초 CPU", "듀티 28~41%" | wall이다. 공항 run 실측 주기 8.2분 기준 듀티 약 17~25% |
| "475~498MiB → 512MiB 근접" | x86·1,536MiB 한도의 합성 별도 프로세스 값이다. 운영 근거는 RSS 405MB 1회뿐이다 |
| "공개 유가 cold 3.89초 → warm 1초" | limit 900·756곳 단일 표본이고 11-23 계획 수정 이전 값이다. 보고서가 cold/hit 해석을 명시적으로 거부했다 |
| "준비 op를 독립 schedule·sensor로 옮기자" | `reference` run_group 동시 1개와 대기열 p95 10~50분 때문에 준비가 굶는다. 지금은 airport job 안에서 종류별 격리가 맞다 |
| "서버 idle_in_transaction·transaction_timeout 도입" | 수집기 lease 연결이 run 내내 idle in transaction이라 공항 run이 5분마다 실패한다. lease 직후 commit이 선행 조건이다 |
| "돌발 0건 200 → 해결" | 해결 방식이 503 전환이라 Map의 NotCurrent 실패는 오히려 늘어나는 방향이다 |
| "Map 실패의 57%가 상류 신호" | Map 테넌트 실패 380건 기준이다. n150 전체 2,314건 기준으로는 6.6%다 |
| "checkpoint write 810초 = I/O 포화" | `checkpoint_timeout` 900 × `completion_target` 0.9의 설계 pacing일 가능성이 크다 |
| "T3 cold 10.83초" | 해당 journal 문맥은 운영 수용(SDK·auth/map) 측정이라 T3 rail 첫 요청이라는 근거가 없다 |
| "T3 cold 첫 페이지가 Map 30초를 넘는다" | 생산자 15초 예산·문장 10초 때문에 대개 30초 안이다. 15초 예산은 batch 경계에서만 검사하므로, 지속시간만으로 503 여부를 판정할 수 없다 |

## 부록 B. finding 색인(최종 심각도)

검증 판정: ✓ 확인, ◐ 부분(정정본 반영), 없음 = 공백 조사(자체 검증).

- **T1**: T1-01 P1◐ 돌발 즉시 503 · T1-02 P2✓ 매시 전량 재구성 · T1-03 P2✓ event loop CPU · T1-04 P3✓ 송신까지 트랜잭션 보유 ·
  T1-05 P3✓ ORM 전체 적재 · T1-06 P3✓ 비압축 · T1-07 P3◐ DB 일시 오류 500·connect timeout 없음 · T1-08 P3✓ airports 클라이언트 ·
  T1-09 P3✓ cursor overflow 500 · T1-10 P3✓ 페이지 간 세대 혼합(현 계약 유지 권장) · T1-11 P3✓ 관측 · T1-12 P3◐ 배포 창 · T1-13 P3✓ ADR 경로 설명.
  누락: 유가 503(P0 → 사건 정리 §3), 호스트 경합, timeout 역전, nginx 임시 파일, Map 주간 적재 미기동, 503 회복 시각 없음.
- **T2/T3**: T23-01 P3◐ admission 55P03 · T23-02 P2✓ 지문 memo miss · T23-03 P3◐ release_sha 무효화 · T23-04 P2✓ 준비 op 결합 ·
  T23-05 P3✓ HTTP 상한 공유 · T23-06 P3✓ traffic 요청 안 복사(소비자 없음) · T23-07 P3◐ event loop · T23-08 P3✓ 메모리 여유 ·
  T23-09 P3✓ 주 1회 304 무용 · T23-10 P3◐ 관측·57014 · T23-11 P3◐ schedule 겹침 · T23-12 P3◐ 종류 무관 GC · T23-13 P3◐ 읽기 API의 쓰기.
- **T4**: T4-01 P2✓ 인덱스 없는 조회 · T4-02 P3◐ 커버링 인덱스 · T4-03 P2✓ 보존·raw 중복 · T4-04 P3◐ null 가격 행 ·
  T4-05 P2✓ timeout 역전(PinVi) · T4-06 P3✓ 트랜잭션 작음 · T4-07 P3◐ 이중 직렬화 · T4-08 P3✓ 중복 조회 · T4-09 P3✓ 불필요 409 ·
  T4-10 P3✓ 기준선 · T4-11 P3✓ Map 클라이언트 · T4-12 P3✓ 공개 이력 rate limit · T4-13 P3◐ PG prewarm 문서 낡음.
- **지도 UI**: MUI-01 P2◐ 공개 유가 page cache 미적용 · MUI-02 P1✓ limiter 대기 중 연결 보유·deadline 없음 · MUI-03 P2◐ 프로세스 동거 ·
  MUI-04 P2◐ 취소 미전파·첫 화면 2요청 · MUI-05 P2◐ 기동 cold · MUI-06 P2✓ 전역 무효화·LRU 8 · MUI-07 P2◐ ITS 15분 차단 ·
  MUI-08 P2✓ 공개 limit 5000 · MUI-09 P3◐ 실패 UX · MUI-10 P3◐ 고속도로 1,000행 · MUI-11 P3◐ 압축·ETag · MUI-12 P3✓ lock 원인 아님 ·
  MUI-13 P3✓ 관측 · MUI-14 P3✓ BFF 16MB.
- **런타임·배포**: RT-01 P1✓ 이력 재구성 · RT-02 P2◐ 단일 풀 · RT-03 P3◐ 배포 무효화 · RT-04 P2✓ timeout 역전 · RT-05 P2✓ 512MiB ·
  RT-06 P3◐ warm rail뿐 · RT-07 P3◐ migration lock_timeout 관례 · RT-08 P3✓ T1 보유 · RT-09 P2✓ 계측 · RT-10 P3◐ 하드 재시작 ·
  RT-11 P2✓ 배포 검증 · RT-12 P3◐ 일시 오류 500 · RT-13 P3✓ 빈 풀 · RT-14 P3✓ bytecode.
- **Map 소비자**: MC-01 P2◐ 503 일괄 처리 · MC-02 P2◐ 돌발 503 · MC-03 P3◐ HTTP 재시도 범위 · MC-04 P2✓ 매시 전량 ·
  MC-05 P3◐ timeout 역전 · MC-06 P3◐ T4 프록시 · MC-07 P3◐ 배포 후 prepare 없음 · MC-08 P2◐ 관측 · MC-09 P2✓ PG 주유소 적재 미기동 ·
  MC-10 P3✓ page size · MC-11 P3✓ 세대 혼합 · MC-12 P3◐ raw·admin(admin은 빼지 말 것) · MC-13 P3✓ 잠금 TTL · MC-14 P3✓ 본문 상한.
- **쓰기·lock·이력**: WLH-01 P2◐ 이력 재구성 메모리 · WLH-02 P1✓ 원본 무보존 · WLH-03 P2✓ 배포 무효화 · WLH-04 P3◐ 준비 op 예외 ·
  WLH-05 P3◐ places 캐시 무효화 · WLH-06 P2✓ 고속도로 175초 트랜잭션 · WLH-07 P3◐ counter 행 잠금 · WLH-08 P3◐ 트랜잭션 안 HTTP ·
  WLH-09 P2◐ 진단 장치 · WLH-10 P3◐ 통계·vacuum · WLH-11 P3◐ 5분 준비 재계산 · WLH-12 P3◐ head 경합 · WLH-13 P3◐ 실패 원장.
- **공백 조사**: G1-F1~F9(유가 503 사건·정책), G2-01~11(기준선·계측), G3-01~11(호스트 경합).
