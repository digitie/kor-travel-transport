# Transport83 health CPU 독립 FULL10 source 검토

- 대상 657ec6d5fdbd19a42c2541cccdb0c34d6a4acff4
- 기준 PR82 c3e3afed9ef6e9c16f6aca1c2278f4095967f895
- 판정: 검토한 제품 변경 SOURCE_PASS / 새 P0·P1·P2 없음.
- 전체 interval3배 요청의 완료 판정은 별도다. root가 이미 지정한 legacy DB5→15초 후속
  delta는 아직 본 대상에 없으므로 현재 전체 요청 완료/운영 적용을 주장하지 않는다.

## 직접 확인

AGENTS/CLAUDE/SKILL·리뷰/실패 runbook, 10파일 전체 diff와 Dockerfile/3Compose/CS probe,
기존 건강상태 handler·공용 sensor 호출 문맥을 읽었다. immutable archive에서만 검증했고 원본은
수정하지 않았다. 상대 리뷰·저자 시험 결과는 읽거나 독립 시험 수에 합산하지 않았다.

- 기존 /health EXISTS handler와 DTO·DB실패 의미는 source byte동일. HTTP CLI는 실제 body를
  해석하지 않고 완전한2xx 헤더만 검사한다. 이는 기존 body EOF/redirect/proxy와 의미가
  다르다고 가이드가 명시한다. shared loopback port는 uvicorn PUBLIC_API_PORT와 동일하다.
- 최종 단일 interpreter/기존 pip·Chromium 설치 뒤 build helper를 한 번 실행한다.
  이후 COPY는 /app·entrypoint만이고 stdlib를 덮지 않는다. root권한·checked-hash compile
  실패를 무조건 성공으로 감추는 shell 처리가 없다.
- lock108개 package의 version과 provider pin은 동일. Common 및 root metadata git pin만
  변경된다. Common[dagster]는 유지하며 grpc-health를 새로 API에 강제하지 않는다.
- 3Compose 전체 파싱 모델은 APItest 및 명시7개 interval 외 exact다. timeout/retries/
  start_period/start_interval·업무 cron·환경·포트·volumes·image·실험용live값이 보존된다.
- CS probe anchor는 기존 SHA exact다. passed/mark는 boot/init 키이며 ttl만료가 아니고,
  tried300초는 최소 간격이다. count·monotonic grace·runs_in_flight 보호는 동일하다.
  interval90초는 실패 감지/복구를 늦출 수 있으나 clock 허용창을 임의 늘리지 않는다.
- proxy heartbeat600초·legacy daemon heartbeat300초는 점검 실행 간격과 별개다.
  설명한 보수적 daemon 지연30+300+60+2×(360+60)=1230초 산식은 정합하다.
  원래 기동 start_interval도 보존되어 냉기동 점검 간격을90초로 바꾼 것은 아니다.
- Common의 기존 단일 infrastructure_retry_sensor 공개 signature와 transport3개 등록은
  유지된다. 새 optional multi/native factory를 이 변경이 자동 등록하지 않는다.
  Common pin 변경을 운영별 전체 동작/장애복구 검증으로 대신할 수 없다.

## 독립 실행

Weather의 이미 설치된 exactCommon c485/Python3.12.13 환경으로 archive source 시험 함수를
직접 호출했다. Transport conftest와 app/SDK는 import하지 않았다.

- 실제 source-contract 함수13조건 PASS: interval7/포트2/컴파일순서1/Common설치1/
  CSanchor1/실험용interval1.
- 같은 함수들에 원base Dockerfile/Compose를 적용하여10조건이 실제 AssertionError RED.
- 세 Compose 전체모델 허용 delta 비교 PASS, lock108 version 동일 PASS,
  backend/app·frontend·packages tree 변경0.
- 순수 모델과 source 읽기만 실행했으며 Docker·SDK·HTTP·DB·SSH·빌더·운영0.
  저자의 실제 HTTP 200/302/503 fixture, fullsuite·CI·ARM cold 점검은 독립 재실행하지 않았다.

## P3 TR83-A-P3-01 — 암묵적 cache 쓰기와 cold deadline 문구

backend/Dockerfile:24의 '런타임 점검에서 재컴파일하지 않는다'는 절대 보장이 아니다.
python -I는 PYTHONDONTWRITEBYTECODE 환경을 무시하므로 cache 누락·무효 시 Python이
암묵적으로 컴파일/쓰기 시도할 수 있다. '런타임에서 이 build helper를 호출하지 않는다'로
한정하고 최종 cache/runtime 권한 검증을 별도 gate로 남기는 것이 정확하다.
docs/runbooks/health-cpu-bytecode.md:14의 전체4초도 모듈 시작 이후 논리 HTTP 예산이고
Python cold 시작을 포함하는 Docker5초 상한 보장이 아님을 명시할 것을 권고한다.
제품 실행상 새 P2로 보지는 않았으며 실제 ARM 빌드/health/CPU로 확인해야 한다.

## 인계

legacy DB interval 후속 및 위 문서 정정은 별도 immutable delta 검토 대상이다.
현재 source PASS를 운영 변경 승인·CPU 인과 개선·provider 비용 개선으로 해석하지 않는다.
파일별 SHA와 실제 결과는 transport83-health-cpu-review-a-r1-20261016.safe.json에 고정했다.
