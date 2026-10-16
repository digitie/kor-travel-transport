# Transport PR82 독립 적대적 제품 리뷰 A

**SOURCE_PASS / 열린 P0·P1·P2 = 0.** FULL5 delta와 관련 호출·데이터 계약 검토다. 운영·배포·성능 전체수용 판정과 구분한다.

- PR: https://github.com/digitie/kor-travel-transport/pull/82
- 후보: bde61206c2e3522624ba22ce5d28a9ec39762c5e
- 기준: 15a928b07c7a30415cfa3d81ba5ee412e79981f5
- 작성자 CP f57fdfc202e09f03cbbfa7c1f07858e3d3b05bf553adba65ff2a2bc408efbe6f 및 제품5파일 SHA 일치 직접 확인.
- AGENTS/CLAUDE/SKILL, 실패패턴/적대리뷰 runbook, architecture/resume 관련 문맥을 읽었다. 다른 reviewer 판정·모형은 읽지 않았다. 원본 WT/제품·타인 파일 수정0, 독립 Gitobject 사본 사용.

## 계약 판단

backend/app/main.py:780에서 COUNT(id) 대신 SELECT EXISTS(SELECT * FROM parking_snapshots) 한 scalar를 실행한다. import exists 외 전체 main은 원문과 정확히 같음을 역치환으로 검증했다.
models.py:690의 실제 id는 primary_key=True/nullable=False이며 초기 migration도 PK다. 따라서 정상 schema에서 bool(COUNT(id))와 EXISTS는 빈표0/하나이상1로 동등하다. nullable collection_run_id/congestion/raw 부가열은 존재 판정에 사용하지 않는다. 잘못된 nullable PK schema로 전제를 바꾸어 결함을 만들지 않았다.

schemas.py:706–710의 status/database/seeded(bool)/release_sha와 OpenAPI는 byte동일이다. seeded가 count 정수에서 bool로 새로 변한 것이 아니며 원래 bool(count)였다. get_db:756–760의 세션 획득·종료와 오류 전파도 그대로다. DB장애/없는table을 healthy로 catch하거나 캐시하지 않는다. 실제 handler:612–627은500 problem+json/원 오류 미노출을 유지한다. CancelledError도 삼키지 않는다.
이는 DB를 읽는 기존 probe이고 생존-only로 바뀌지 않는다. 전체 row를 읽어서 모든 데이터 무결성을 검사한다는 보장도 기존 계약에 없다.

호출은 기존 Compose HTTP probe와 배포 health 확인·frontend proxy 경로이며 응답/주소/주기/timeout 변경0이다. schema/session/OpenAPI/의존성/lock/4Compose는 기준과 byte동일하다. PR81 pin/cadence/다른 provider·CS/UI 변경은 섞지 않았다.

## 테스트·문서 평가

신규4회귀는 endpoint ASGI를 독립 SQLite 의존성으로 덮어 0/1/1024행의 DTO·단일 EXISTS·COUNT 부재 및500 오류보호를 확인한다. lifespan/실제 전체schema/운영PG 시험을 대신하지 않는다. OLD3RED는 이전 동작의 DTO 결함이 아니라 불필요 COUNT를 금지하는 SQLshape 회귀의 RED다.
docs3개는 미완료 전체검증·2리뷰·실배포를 남기고 warm id-only 50만행/CPU1 native로컬 수치를 운영 CPU 감소율로 확대하지 않는다. COUNT ActualRows250000×loops2와 EXISTS1행·buffer 중복불합산 설명을 보존한다. 저자실측은 문서 범위 검토일 뿐 본인 새PG 실행으로 합산하지 않았다.

## 실제 독립 실행 / 미실행

Gitobject 함수 본문 AST·실제 ParkingSnapshot models/HealthResponse DTO로 독립 script를 실행했다. conftest를 전혀 로드하지 않았고 자기 SQLite :memory:만 사용했다.

- 0행/1행/0id/음수id/sparse3/1024행에서 old/new DTO 동일·bool타입·각1scalar·새 EXISTS/COUNT없음/추가filter·join없음 확인.
- PostgreSQL dialect SQLcompile, OperationalError/CancelledError/없는table old/new 실패전파, 실제 오류handler500/redaction, 실제 PK nullable=False 확인.
- 총 **41조건 PASS**, 변경Python compile 및 git diff --check PASS.
- 전체 backend suite는 저자 진행 소유로 중복 NOT_RUN. 본인 PostgreSQL/운영SSH·Docker·SDK/provider·외부HTTP·배포0. 실제 ASGI 전체app/실제PG/성능 benchmark는 이번 독립 script에서 NOT_RUN.

남은 gate는 작성자의 전체 backend·정확HEAD CI, 다른 독립제품리뷰 및 운영 적용 후 동일 workload 실측이다. 소스PASS를 총 hostCPU 개선 또는 live E2E 완료로 확대하지 않는다. 모든 본인 도구 terminal.

## 고정 증거

- backend/app/main.py SHA e5fc5af49b5aa4cf6165fb2e6ce1755f21ec4171c518f76dd347abefe0d4c4af
- backend/tests/test_health_presence.py SHA 92abd3ce876c161b835da3eca4ff8483831a61e6ef950ee55ed7efe0e8d94025
- docs/journal.md SHA 86fb85c73a2c275b8a05ebf3b71b61bf973555121539dec672717cda2ffd556d
- docs/resume.md SHA 2d6c4ab790a6ddf6991e91e29f00993cca6e2f1856f3f6ca31ef4cd2219a052f
- docs/reviews/2026-10-16-health-presence.md SHA 13e8cf5ca595e99fd752048d026c101b07ad374827211c22a6c1bb139a78d72d
- transport82-review-a-r1-20261016.archive.json SHA 9768b4bc5b8940e8ff29a432f8b45a413588fd5d02c69d71817646e3d014f133
- transport82-health-presence-model-a-r1-20261016.py SHA 69eb3ca5db8a9804f9b08bde700b9ce733e587608cc498c476759a7fc032c07c
- transport82-health-presence-model-a-r1-20261016.json SHA ab0da7d1c82aff6b6ab9c1bac89e09d06620398ce446127c09b02a6093a821f4
- transport82-health-presence-review-a-r1-20261016.checkpoint.json SHA 03a69c6e251d093c99dd525c261ffed5d965486a68507e8c29f8ca65e0f6b9bc
