# /health seeded 존재 조회

## 문제와 변경

기존 backend/app/main.py의 /health는 ParkingSnapshot.id 전체 COUNT를 계산한 뒤
bool(count)만 반환했다. 기본 Docker probe10초 주기마다 같은 전체 집계가 반복될 수 있다.
존재 여부가 목적이므로 SELECT EXISTS로 바꾸고 응답 status/database/seeded/release_sha,
DB 접근·장애 처리와 readiness 의미는 유지한다. seeded는 스냅샷0행이면 false,1개 이상이면 true다.
DB를 읽지 않는 liveness로 바꾼 것이 아니다.

최신 main15a928b에서 분기했으며 PR81의 pin/cadence/image/UI health 변경은 포함하지 않는다.
해당 main.py 원본 전체 SHA256은 운영에서 읽은 health 파일과 같은
81c2710886b757df398baf3cb2f5ef37ce0993d29cc9f305df617303bb800282였다.
이는 한 파일의 일치이며 운영 앱 전체 HEAD 증명은 아니다.

## 검증 범위

- 실제 ASGI·독립 SQLite0/1/1024행에서 응답 DTO와 단일 EXISTS·COUNT 미호출을 확인했다.
- DB 장애는 기존500 problem+json을 유지하며 원 오류를 응답에 노출하지 않는다.
- 교정된 동일 회귀의 OLD3FAIL/장애1PASS→NEW4PASS. 첫 host/오류본문 fixture 가정 실패는 별도이며 제품 RED로 세지 않았다.
- native PostgreSQL16.14 amd64·캐시 이미지·networknone/ports0/CPU1/memory=swap512MiB의 독립500000행 id-PK fixture에서
  statement_timeout5초/lock_timeout1초·READ ONLY·rollback으로3쌍을 비교했다. 각 쌍 순서는 COUNT/EXISTS, EXISTS/COUNT, COUNT/EXISTS였다.

| 쌍 | COUNT 서버 실행 ms | EXISTS 서버 실행 ms |
|---|---|---|
|1|19.737|0.015|
|2|41.887|0.010|
|3|19.820|0.007|

첫 쌍 COUNT는 SeqScan ActualRows250000×ActualLoops2와 shared hit2213,
EXISTS는 ActualRows1×ActualLoops1와 shared hit1이었다. 상위 노드의 buffer는 하위 노드와 중복될 수 있어 합산하지 않는다.
이 수치는 작은 id 전용 합성 테이블·따뜻한 cache·DockerCPU1의 로컬 근거다.
운영 테이블 row width/index/bloat·수집 부하·총 hostCPU 개선률을 증명하지 않는다.
자기 PG는 정상Exit0/PID0/noOOM으로 정지했고 운영/외부 provider 요청은0이다.
초기 호스트 서버 바이너리 부재·stdin 누락·임시init server readiness 오판과 해당 자기PG 정상 정리는 별도 원문으로 보존한다.

## 완료한 검증과 남은 운영 범위

검토 대상 runtime candidate는 bde61206c2e3522624ba22ce5d28a9ec39762c5e다.
이후 증거 통합은 docs-only이며 main.py·신규 회귀·의존성·Compose blob은 그대로다.

- 로컬 Python3.13.14 전체 backend: **738 PASS·10 SKIP·기존 warnings6**, pytest1509.30초/호출 wall1512.706초, exit0.
  강제 per-test 임시 SQLite와 빈 TEST_DATABASE_URL을 사용했고 공유/운영 PostgreSQL 접근은0이다.
- 해당 runtime commit의 PostgreSQL16/Python3.12 CI run38881965311: **746 PASS·2 SKIP·warnings6**,881.75초.
  같은 backend job에서 locked sync·Alembic upgrade/check·OpenAPI --check가 통과했다.
  기존 frontend와 관리자 frontend CI의 test/type/build도 SUCCESS다. push/PR 중복 run을 별개 제품 검증으로 합산하지 않는다.
- Docker2차: 캐시된 nativeamd64/Python3.12 시험 이미지에 현재 backend를 read-only mount하여 신규4 ASGI/SQLite 회귀 **4 PASS**.
  networknone/ports0/readOnly/capdropALL/noNewPriv/CPU1/memory=swap1GiB/PIDs128, 자연 exit0/PID0/noOOM.
  이는 정확 candidate를 새로 빌드한 이미지나 운영 ARM64 검증이라고 주장하지 않는다.
- 독립 제품 리뷰 A/C 모두 **SOURCE_PASS·열린 P0/P1/P2=0**. 작성자 결과와 분리해 원문을 byte 그대로 보존했다.
  A는 실제 모델/handler·AST 및 자기 SQLite41조건, C는 격리 신규4회귀와13조건을 직접 확인했다.
- frontend/DTO/schema/의존성/HC주기/수집/admission 변경0.
- 증거 문서 head의 CI는 push 후 별도로 추적한다. 운영 build/deploy·실제 HC/live API·동일 workload CPU 실측은 **NOT_RUN**이며 root가 별도 소유한다.
  두 소스 리뷰와 합성 benchmark로 운영 개선률 또는 live E2E 완료를 주장하지 않는다.

| 원문 | SHA256 |
|---|---|
|[독립 리뷰 A](evidence/2026-10-16-health-presence-review-a.md)|8a55727cc52b147d3192bcc4eac6192f0983053d5eb872410f0e07db0c1deb3a|
|[독립 리뷰 C](evidence/2026-10-16-health-presence-review-c.md)|56ac1b2ca97ad6ff23c1ccd5bc3dcfb50b9d1544168057a85890f25abf4fcd35|
