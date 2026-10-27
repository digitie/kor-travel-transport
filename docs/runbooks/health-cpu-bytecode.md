# 점검 CPU 비용과 운영 주기

## 변경 범위

PR82의 /health seeded EXISTS 조회를 그대로 포함한다. Common37 merged
c48595880aaad4367802ad71af2525a8a5e17c6a의 순수 표준 라이브러리 HTTP CLI와
build_bytecode --stdlib을 소비한다. Python 최종 이미지에서 모든 설치가 끝난 뒤 root가
stdlib을 한 번 컴파일한다. 런타임에서 이 helper를 호출하지 않는다.
캐시 누락·무효 시 Python은 암묵적으로 다시 컴파일하거나 쓰기를 시도할 수 있다.
-I는 PYTHONDONTWRITEBYTECODE 환경을 무시하므로 최종 캐시와 runtime UID 권한은 이미지에서 검증한다. 실제 런타임 Python의 cache tag/magic을 사용하며 다른 minor에서 만든
pyc를 복사하지 않는다. API와 code-server는 같은 backend 이미지를 소비한다.

API probe는 python -I -m kortravelcommon.http_health --port <서비스 포트>
--path /health --timeout-seconds 4다. 기본 이미지 포트8000과 shared host 포트
PUBLIC_API_PORT(shared overlay 기본 12302, #90 이후)를 각 Compose의 실행 포트와 맞춘다. 기존 urllib의 proxy·redirect와
body EOF 읽기는 제거된다. 새 CLI는 loopback GET, 최대16KiB 완전한 헤더, 전체4초 예산,
2xx만 성공이며 redirect/retry를 하지 않는다. 4초는 모듈 시작 이후 HTTP 논리 예산이다.
Python cold startup/import를 포함하는 Docker timeout5초의 성공 보장이 아니다. 헤더만 읽으므로 body 완전성 검증과 동등하지 않다.
/health handler의 DB 조회·seeded DTO·오류 상태는 바꾸지 않는다. DB 없는 liveness로
표현하지 않는다. Common 없는 구 이미지에 선언부터 적용하면 모듈 없음으로 실패하므로
**소비 이미지에 CLI 존재를 확인한 뒤 Compose 선언을 적용**한다.

## 전체 운영 점검 간격

| 역할 | 이전 interval | 새 interval | 그 외 |
| --- | --- | --- | --- |
| backend·frontend | 10s | 30s | timeout5s/retries10/start20s 유지 |
| code-server | 30s | 90s | timeout10s/retries5/start600s/start_interval5s 유지 |
| admin gateway·admin web | 15s | 45s | timeout5s/retries5, 기존 start 유지 |
| legacy webserver | 15s | 45s | timeout5s/retries8/start30s 유지 |
| legacy 독립 PostgreSQL | 5s | 15s | timeout5s/retries20/start10s 유지 |
| legacy daemon | 120s | 360s | timeout60s/retries2/start60s/start_interval15s 유지 |

실험 전용 docker-compose.live.yml의 Postgres5s/backend10s는 대상이 아니다.
business cron, provider cadence, UI 요청 timeout은 변경하지 않는다. 후속 FE/admin Node probe 변경은 아래 절에 별도로 기록한다.

CS의 legacy health 내 PID1 kill·orphan reaper·ListRepositories 검사는 원문 그대로 보존한다.
passed/mark는 boot ID와 incarnation 식별자이며 mtime 만료 검사가 없다. tried의300초는
재시도 최소 간격이므로90초 점검은 재시도를 늦출 수 있다. 실패 횟수3 및 monotonic
90/300/1800/7200초 판정은 그대로이며 점검 간격 연장은 실패 관측·복구를 늦출 수 있다.
proxy heartbeat TTL600초는 Docker 점검 주기가 아니라 daemon/서버 heartbeat의 계약이다.
애플리케이션 reconciliation의5시간 grace도 별개다. 따라서 이번 변경에 deadline을 늘리지 않는다.

legacy daemon의 native heartbeat 허용300초는 그대로다. Docker가 probe 종료 후 interval을
세는 보수적 가정에서 문서의 unhealthy 관측 상한은
30+300+60+2×(360+60)=1230초로 늘어난다. Docker unhealthy 자체가 restart를 실행하지는 않는다.
일정·heartbeat 생성 주기를360초로 바꾼 것이 아니다.

## 배포 원본과 검증 한계

안전한 현재 파일 해시 증거 transport-current-source-hashes-root-r1-20261016.json에서
definitions.py/main.py/pyproject/uv.lock 네 파일은 main15a928b와 일치했다.
PR81 027ad55는 main.py만 일치하고 나머지 세 파일이 달라, 확인 범위에는 PR81의
cadence/Common41 핀이 없다. 전체 운영 이미지 Git HEAD를 증명하지는 않는다.
현재 브랜치는 PR82 c3e3afe 위이며 COUNT→EXISTS 패치를 보존한다. PR81의 미배포 기능을
이 점검 변경에 섞지 않는다. 배포 시 다른 미확인 실행 파일의 provenance는 별도로 정산해야 한다.

새 회귀는 운영·legacy 모든 interval 및 나머지 시간값, 실제 설치 Common의 정본 소스 해시와 VCS 또는 wheel 설치 출처,
컴파일 순서, quiet2xx/redirect/503 거절, CS guard 원문, 실험 전용 간격을 확인한다.
로컬 loopback 시험은 provider 호출이 아니다. 실제 ARM 이미지 pyc와 CPU 개선,
Docker 검증·운영 배포·live E2E는 별도 단계이며 소스 시험만으로 완료라고 표시하지 않는다.

## 의존성과 시험 정산

Common430→c485에서 RecoveryPolicy/coalescing_schedule/reconciliation_sensor는 AST가 동일하다.
기존 단일 infrastructure_retry_sensor는 공개 signature를 보존하지만 Common32/35 내부 helper로
위임하며 명시적 framework ChildProcessCrash 분류·step checkpoint가 추가된다. 이를 retry 구현
byte불변이라고 표현하지 않는다. Transport의 세 멱등 job allowlist/한도1/provider 실패 제외
설정은 보존하며 새 multi/native sensor를 등록하지 않는다.

657ec6d5 source의 WSL1차 전체 backend754 PASS/10 SKIP(1517.06초), frontend130 PASS와
admin202 PASS·양쪽 type/build PASS를 확인했다. 첫 build의 외부 node_modules symlink
거절은 원문 보존하고 own 디렉터리 복사 후 정상 build했다.
후속 delta는 legacy DB interval/회귀·문구·wheel 설치의 정본 hash 확인 및
Docker 회귀에 필요한 무비밀 Compose fixture COPY뿐이다. backend/app·업무 정의는 불변이다.
이 결과를 실제 PostgreSQL/ARM/운영 성능 증거로 합산하지 않는다.

## 소스 리뷰와 로컬 검증 정산

최종 runtime d797의 A/C 독립 source 원문, host·Docker 전체 실패와 동일artifact7개 재검증, CI 및 아직 남은 ARM/live gate는 [검증 정산](../reviews/2026-10-16-health-bytecode-closure.md)에 기록한다. 원 Docker 전체FAIL을 후속 전체PASS로 바꾸지 않는다.

## FE/admin core HTTP 점검 (2026-10-17)

제품 커밋 2a6e9ba2e39c7fc46a8072c9fd2adb811ecf9ee3은 기본·shared frontend와
transport-admin-web의 Healthcheck.Test 세 곳만 node:http로 바꾼다. URL과 포트 변수,
frontend30초/admin45초 interval, timeout5초, retries/start_period는 유지한다.
Node fetch의 200 헤더 수신만으로 성공하던 경로를 제거하고, GET 응답의 2xx와 완전한
body end/complete 및 not-aborted를 확인한다. redirect를 따라가지 않으며 agent:false와
Connection:close를 사용한다. body를 누적하지 않고 최대1MiB까지 읽는다.
오류·초과·중단·기한 도달은 quiet exit1, 완전한 성공만 quiet exit0이다.

단일 monotonic4초 기한은 첫 JavaScript 실행부터 적용하며 core 모듈 로딩과 body 읽기를
포함한다. Node 프로세스 부트스트랩 이전 시간은 포함하지 않는다. 따라서 부하가 있는
ARM에서 Docker timeout5초 통과를 보장하지 않는다. 기존 CS reaper/guard는 바꾸지 않는다.

실제 Compose Test를 로컬 Node loopback fixture에서 실행한 신규37개와 기존 health
계약17개가 통과했고 Ruff/node --check도 통과했다. 기존 admin probe는 200 헤더 뒤
body가 멈춘 fixture에서 exit0으로 실패를 재현했다. 초기 source 작성 실패로 구 소스에서
실행된 전체34FAIL/3PASS도 보존하며 후보 결과로 합산하지 않는다.
--noconftest를 사용해 app/SDK/DB를 초기화하지 않았다. 이 좁은 delta에서 전체 backend,
UI build, Docker 검증을 다시 실행하지 않았으며 CI와 두 독립 리뷰는 별도 gate다.

배포 provenance는 runtime_image_source=ac57b56a4d3b7e15e326346de8441a34fb0fe276과
deployment_config_source=2a6e9ba2e39c7fc46a8072c9fd2adb811ecf9ee3을 구분한다.
backend/app, backend/Dockerfile, Python 의존성과 Common 핀은 ac57과 byte 동일하다.
이미지에 포함된 과거 Compose 사본이 새 runtime Git HEAD를 뜻하지 않는다.

별도 단일 native 비교의 기존 fetch2.533822 CPU초/RSS75756KiB와 core 후보0.392888
CPU초/RSS43976KiB는 비통제 한 쌍의 관측이다. 해당 후보는 최종 strict script와 다르므로
이 수치를 최종 script의 실측이나 전체 CPU 개선으로 주장하지 않는다.
운영 적용·최종 strict script native 검증·live UI/CPU 비교는 root의 후속 단계다.
