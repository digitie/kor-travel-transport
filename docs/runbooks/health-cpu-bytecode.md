# 점검 CPU 비용과 운영 주기

## 변경 범위

PR82의 /health seeded EXISTS 조회를 그대로 포함한다. Common37 merged
c48595880aaad4367802ad71af2525a8a5e17c6a의 순수 표준 라이브러리 HTTP CLI와
build_bytecode --stdlib을 소비한다. Python 최종 이미지에서 모든 설치가 끝난 뒤 root가
stdlib을 한 번 컴파일한다. 실제 런타임 Python의 cache tag/magic을 사용하며 다른 minor에서 만든
pyc를 복사하지 않는다. API와 code-server는 같은 backend 이미지를 소비한다.

API probe는 python -I -m kortravelcommon.http_health --port <서비스 포트>
--path /health --timeout-seconds 4다. 기본 이미지 포트8000과 shared host 포트
PUBLIC_API_PORT(default14001)를 각 Compose의 실행 포트와 맞춘다. 기존 urllib의 proxy·redirect와
body EOF 읽기는 제거된다. 새 CLI는 loopback GET, 최대16KiB 완전한 헤더, 전체4초 예산,
2xx만 성공이며 redirect/retry를 하지 않는다. 헤더만 읽으므로 body 완전성 검증과 동등하지 않다.
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
| legacy daemon | 120s | 360s | timeout60s/retries2/start60s/start_interval15s 유지 |

실험 전용 docker-compose.live.yml의 Postgres5s/backend10s는 대상이 아니다.
business cron, provider cadence, UI 요청 timeout은 변경하지 않는다. frontend/admin Node probe의
원문도 이 변경에 포함하지 않는다.

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

새 회귀는 운영·legacy 모든 interval 및 나머지 시간값, 실제 설치 Common VCS commit,
컴파일 순서, quiet2xx/redirect/503 거절, CS guard 원문, 실험 전용 간격을 확인한다.
로컬 loopback 시험은 provider 호출이 아니다. 실제 ARM 이미지 pyc와 CPU 개선,
Docker 검증·운영 배포·live E2E는 별도 단계이며 소스 시험만으로 완료라고 표시하지 않는다.
