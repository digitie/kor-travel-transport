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

- focused4PASS. 전체 backend 검증은 진행 중이며 완료로 표시하지 않는다.
- frontend/DTO/schema/의존성/HC주기/수집/admission 변경0.
- 두 독립 제품 리뷰·정확 candidate CI·Docker2차 및 운영 적용/CPU 실측은 별도 후속이다.
