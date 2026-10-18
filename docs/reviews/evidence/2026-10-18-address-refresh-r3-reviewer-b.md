# Transport86 formal FULL 독립 Popper/Backend·SQL·ops 리뷰 r3

**PASS — TRANSPORT_SOURCE_AND_OWN_FIXTURE_ONLY. OPEN P0=0 / P1=0 / P2=0.**

원 T86-B-P2-01 legacy ferry admission CLOSED를 유지하고, **T86-B-P2-02 현재 source 밖의 last_resolved_at 노출을 이 소비자 exact155에서 CLOSED**로 판정한다. Common/Weather PASS를 Transport formal 판정으로 대신하지 않고 actual Transport 모델·adapter·schema·BFF를 확인했다. 운영 수용/배포/실제 provider/Daemon ON/수집 CPU·RSS 완료 판정이 아니다.

## 불변 범위·시각·격리

- manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r3.json 관찰 SHA256 **5effb1be7ca00fd6872f6dd1ef25cc9b9e7f79bae683c3b329d0369e7af92c87** (요청과 일치).
- base61a566dee0b1cc40f858652c0683883c26e56411, tree40342c2655ff57e74889c0658faff003464401fb.
- exact head1554783755ccf30be24bcafbab039322c6a685d3, treebe691b015801c62b456fbc4c8ec7646f92b7e4d7.
- Common pin522525aed3db934767c1c9e742b3bfc68e91679c.
- repo /home/digitie/dev/kor-travel-transport-codex-reverse-address-20261018.
- 첫 관찰 UTC2026-10-18T04:11:49.081575+00:00, 후반 source 관찰04:16:46.095173. 종료는 끝에 기록.
- CLAUDE/AGENTS/SKILL, hostile-review 및 agent-failure-patterns runbook을 읽었다. 별도 에이전트로 배정된 Popper 역할이며 새 상대 r3 결과/모형을 읽거나 요청하지 않았다. 기존 확정 r1/r2 원문만 이력/closure로 참고했다.
- immutable Git object와 소유 ext4 TemporaryDirectory만 사용. source/index/branch/WIP 및 기존 보고서를 수정하지 않았다. 기존 read-only backend venv interpreter, -I -B, sterile HOME/TMPDIR/PATH, pytest plugin 자동 로드 차단/--noconftest/-c /dev/null/-p no:cacheprovider를 사용했다. settings는 _env_file=None, DB는 자기 temp SQLite뿐이다.
- actual source/Common를 temp로 물질화해 실행했다. 환경값/키/secret/private/production/SSH/SDK/provider/Docker/Daemon/브라우저 접근0. audit hook으로 socket/subprocess를 차단했다. Node VM fetch는 대역이고 실제 네트워크를 만들지 않았다.
- SQLite fixture를 PostgreSQL 행락/동시성 PASS로 취급하지 않는다. read-only/no-ops는 리뷰어 범위이며 root 기존 위임을 철회하거나 새 승인요건을 만들지 않는다.

## FULL delta 및 source 계약

base→head **37파일1761+/10-**를 전수 분류·검토했다. 제품·tests·Compose·OpenAPI·UI와 이미 확정된 r1/r2 원문 보관/처분 docs를 포함한다. 모든 changed 경로에 path+NUL+blob SHA256+LF를 결박한 SHA는
**b73c4de710578851dff9747bcc28a13553eb57b3242c12cb5fb51adc4ad1c200**.
git diff --check exit0.

r2 8c→155에서는 package/lock/health assertion의 c067→5225 pin, 새 legacy-only 집계 회귀와 docs만 바뀐다. 아래3파일을 pin 역치환하면 r2 bytes 전체가 동일하다:
backend/pyproject.toml, backend/uv.lock, backend/tests/test_health_cpu_contract.py.
r2 대비 service·migration·OpenAPI·BFF·UI component도 byte 동일임을 따로 확인했다. 따라서 기존 기능의 source 검토를 계승하되, current consumer 모델과 pin 연결을 이번에 재실행했다.

### 1. 5종 source/좌표/원천 보존

backend/app/services/address_refresh.py:24–51은 FuelStation/BusTerminalReference/FerryPort/RailStationReference/RestAreaReference union_all을 사용한다. target_key는 kind prefix+ID라 같은 숫자 ID끼리 충돌하지 않는다. 좌표는 longitude124..132/latitude33..43 BETWEEN이며 NULL은 SQL unknown으로 탈락한다. FerryPort만 :37–42에서 location_source IS NULL OR !=data_go_kr_port_guideline을 추가해 admin_manual/NULL을 보존한다.

:46–50에서 같은 current selector를 실제 DatabaseAddressSource에 주므로 page/retries/pending/summary/sample이 분리된 엉뚱한 admission을 쓰지 않는다. source 모델은 read-only이며 실행은 sidecar entries/control만 쓴다. 원천 주소/raw JSON/관리자 위치/정방향 좌표/fact 필드를 바꾸는 쓰기 코드는 없다. 실제 fixture의 전후 전체 source snapshot으로 확인했다.

### 2. 원 T86-B-P2-01 / r2 T86-B-P2-02 disposition

- **P2-01 CLOSED 유지**: legacy 항만은 신규 provider 호출 및 기존 파생 sample/summary에서 제외된다. NULL/admin_manual 유효 좌표는 포함된다. 원천/legacy sidecar를 삭제해 표시를 맞추지 않는다. exact 제품 regression과 actual source를 다시 실행했다.
- **P2-02 CLOSED**: 이전 Common c067 reverse_address.py summary의 provider-global MAX가 현재 source/좌표 밖 과거 확인일을 읽었다. current5225:551–556은 _joined(provider_id,target_key)+현재 longitude/latitude equality 뒤 MAX를 적용한다. status=ok 조건을 억지로 넣지 않아 같은 좌표의 재시도 실패가 가진 마지막 정상 resolved_at은 유지한다.
- actual Transport 모델에서 legacy 필터 전환·삭제·경도 이동·위도 이동·NULL 좌표·범위 밖 좌표 **6개 old→new 반례**를 직접 실행했다. c067은 과거 시각이 남고5225는 None/items=[]임을 같은 입력에서 확인했다. 과거 sidecar는 그대로다.
- current 정상 후200일 시점 실패, 미래400일 orphan 및 다른 provider 동일 key의 미래500일 행을 넣어도 current last-good만 남는다. source/entry/control 전체 snapshot이 summary 전후 동일하며 SQL trace는 SELECT만 발생했다.

원 r2 보고서 /home/digitie/dev/reverse-address-transport-review-popper-r2.md SHA
**e3b770f16b506db16483c1c5f2be4098ccf6ad3eaae2ba213f0d7af6ada7e391**는 head의 보관 blob과 byte 동일하다. 원 REQUEST_CHANGES를 소급 PASS로 바꾸지 않았다. docs/reviews의 r1/r2 처분은 원 시점의 OPEN을 보존하고 새 pin 재검토와 분리한다.

### 3. migration/lineage/DTO/packaging

- backend/alembic/versions/0025_reverse_addresses.py:1–45: down_revision0024_collection_run_owner, entries 복합PK(provider_id,target_key), 시간/좌표/payload/status/retry/hash 필드 및3indexes, control의 cursor/manual cycle/owner/lease. source 테이블 ALTER/DELETE 없음.
- db/session.py:14 ALEMBIC_HEAD도0025와 맞는다. PostgreSQL startup은 actual alembic_version 불일치 시 fail-closed다. main source에 임의 create_all PG 우회가 없다.
- owned SQLite에서 **actual Alembic upgrade/downgrade**를 수행하고 Common5225 metadata와 컬럼 순서/nullability/PK/index를 대조했다. 별도 source_original 행은 up/down 뒤 그대로다. 실제 PostgreSQL DDL compile도 수행했으나 PG에 연결/실행하지 않았다.
- actual AddressRefreshSummary.model_json_schema()와 docs/openapi.json의 component가 **전체 동일**했다. nullable last_resolved_at은 DTO/TypeScript가 허용하고 표시는 미확인이다. 기존 일반 map/source address를 파생 주소로 교체하지 않는다.
- backend manifest의 Common[dagster,reverse-address], lock의 rev/fragment 및 extras가 같은5225다. r2 pin 역치환 byte 동일이라 다른 dependency/SDK 버전을 몰래 바꾸지 않았다. health actual file SHA assertion과 VCS/file-wheel provenance 분기도 약화하지 않았다. 추가로 exact test_installed_common_has_pinned_cli_modules AST를 실제 read-only 설치 metadata/http_health.py/build_bytecode.py에 실행해 commit5225·두 고정 SHA 및 manifest/lock assertion PASS를 확인했다. SDK/socket import는 없다. native wheel/이미지 빌드는 본인 NOT_RUN이다.
- Docker Compose는 backend와 shared Dagster execution env에 AUTO/BATCH/TIMEOUT/VWorld를 전달한다. 다른 cron/복구 정책/health interval/resource를 이 feature에서 바꾸지 않았다. Daemon을 실제 시작하는 코드/명령은 없다.

### 4. Dagster/재개/lease/자원

backend/app/dagster/address_refresh.py:9–22는 run에 force를 넘기고 pending은 configured guard 뒤 current source.has_work(automatic=AUTO)를 쓴다. Common address_refresh_definitions는 자기 transport location의 job/sensor로 등록되며, definitions.py:572–583은 기존 recovery jobs/schedules를 보존하고 이 둘만 추가한다.

actual callback/page/retries/pending_failures 연결을 읽었다. Common engine은 source SQL에 eligibility/limit을 적용하고 batch_size 최대500, retries 최대10, budget30초 기본/최대300초 guard 및 cursor wrap을 유지한다. 요약은 SQL aggregate, sample은50개 제한이라 전체 source 목록을 Python에 상주시키지 않는다. consumer contextmanager finally에서 engine.dispose, resolver owned 경우만 close한다.

own current SQLite 실행:
- AUTO=false manual 실패2개: remaining=1, backoff0/119초 pending=false,120초 true, 정상 재개 뒤 processed2/remaining0/pendingfalse.
- resolver 반환 중 시계를100초 진행해90초 lease를 만료: actual OwnershipLost, late 결과 sidecar 게시0/cursor 미진행, owner release, 다음 정상 run에서2개 재개 완료.
- retries(limit1)/page(limit1) 실제 한도를 확인. 오류 원천을 모두 legacy로 제외하면 한 번 cycle 정리 tick을 허용하고 processed/request0·remaining0으로 닫힌 뒤 pendingfalse. 영구 pending이 아니다.

이는 SQLite 순차 시간 주입이며 실제 PG concurrent lock/fencing 또는 native SDK event를 재현했다고 말하지 않는다. Common source/Weather의 검증만으로 이 consumer 판정을 대체하지 않았다.

### 5. auth/BFF/UI/native 경계

- main.py:645–648은 설정token길이>=32+compare_digest, :776–798 신규 요약route도 require_admin_token 의존성. sync 요약은 FastAPI threadpool에서 실행된다. BFF auth/origin 파일은 base와 byte 동일하다.
- BFF route.ts:52–91은 session→Origin→JSON/1024byte/UUID-only→단일 Node submission flag 순서다. 이전 같은 request tag 조회, 현재 active조회, 고정 자기 job/location/repository/force config만 launch한다. 일반 readonly GraphQL allowlist에 mutation을 넣지 않는다.
- GET은 server token만 내부 API에 전달하고 body262144byte/12초·private no-store다. GraphQL은131072byte/10초, raw error/key를 UI로 내보내지 않는다. 단일 Node process guard의 finally release와 **복수 replica 전역 exactly-once 미보장**은 docs:59–60에 명시되어 있다.
- actual TS route/scope를 transpile한 VM에서 **33 assertions PASS**: 미인증/Origin/본문·UUID/초과body 거절, fixed selector/force/tags, SUCCESS/FAILURE/CANCELED replay, active409, 동시POST1launch, 오류redaction+finally재진입, GET 미설정token/oversized응답/nullable summary. fetch와 auth/origin 판단은 대역이므로 실제 인증 암호검증/HTTP/Next/브라우저 PASS는 아니다.
- component:13–31/35–79는 loadError/launchError 분리, abort된 GET 무시, POST오류 보존, 실패/취소/성공 replay를 신규예약과 구분한다. 최초실패를 늦은 GET이 지우지 않는다. 최대50 table 및 PC/mobile 가로스크롤, focus/alert/status가 있고 원천 주소 대체 표면은 아니다.
- e2e source13개(두 viewport 합)는 loopback 명시환경에만 켜지고 native 예약/재조회/중복/CSRF와 fixture 실패/503/late GET을 나눈다. 본인이 브라우저 또는 SDK를 실행한 것은 아니다.

## 직접 실행 정산과 준비 오류 보존

| 실행 | 실제 결과 |
| --- | --- |
| actual 모델/MAX closure6 + failed/orphan/provider1 + exact 제품4, 그리고 union fixture | 11 PASS / union 자체1 FAIL,1deselected /1.71초 |
| union 기대정정 후 exact 제품4+union1 | 5 PASS/1deselected/0.70초 |
| actual pending·expired lease·제외오류cycle fixture | 2 PASS/자체 기대1 FAIL/0.84초 |
| cycle정리 의미 확인 뒤 해당 fixture | 1 PASS/0.61초 |
| actual Alembic SQLite up/down/metadata·PG DDL compile | PASS |
| actual Pydantic/OpenAPI·pin/extra/lock | PASS |
| actual TS BFF VM | 33 assertions PASS |
| exact 설치 Common pin·http_health/build_bytecode SHA assertion | PASS |

중복 재실행한 제품4개를 합산해 새 전체 suite 숫자를 만들지 않는다. 두 자체 실패는 다음과 같으며 제품 변경/실패 은폐가 아니다.

1. union fixture가6행이면 provider6회라고 잘못 기대했다. 실제4종 동일좌표가 cache를 공유하므로 processed6,requests3이 정당하다. 올바른6개 key/원천불변과 cache재사용을 확인한 교정 실행이5PASS다.
2. 모든 오류원천을 제외하면 pending이 즉시false라고 잘못 기대했다. actual Common has_work:493–496은 수동 cycle 정리를 위해1회 true를 반환한다. 정상 빈 실행이 외부호출0으로 cycle을 닫고 이후false임을 검증했다.

추가 source 수정이나 root의 운영 data를 읽어 테스트를 맞추지 않았다.

## 외부 증거와 현재 수용 한계

manifest 및 root 전달에 따르면 current155의 PR CI39094548318/duplicate push39094545635는 SUCCESS, backend849PASS/2SKIP/1603.62초와 migration/OpenAPI/frontend/Admin gate가 완료다. **작성자/CI 귀속이며 본인이 전체849나Docker22/UI13/PGdrill을 재실행한 수치가 아니다.** workflow live-e2e skip은 PASS로 세지 않는다.

공개 consumer evidence 실제 SHA **31892dbe8c2348052e902438840c5c4028e94fd4ff2e24172015e34579074d1a**와 legacy verification SHA **ab836d6d3afad71660aef86ff27fbeb5bd18a0bb986922965b4646e9fbcaa6bc**를 확인했다. consumer evidence의03:48 당시 Transport CI pending과 후속완료 manifest는 시점이 다르다. 원본을 성공으로 덮지 않는다. 초기 oldpin assertion1FAIL/21PASS 및 뒤22PASS, legacy-only old1FAIL 이력도 유지된다.

과거6a+c067 fullDocker835/13,8c848/2 및 current155의22/Docker22/UI13은 서로 다른 실행이다. 현 source에 historical raw r1/r2가 남아 있고 원 P2와 새 closure를 구분한다. 새 pin의 actual DB/provider 운영 적용이나 모든Track1/2 완료를 주장하지 않는다.

**NOT_RUN:** 실제 PostgreSQL 행락/동시transaction·schema upgrade·native run/event/실제provider·quota·키·운영 migration/API/UI/배포·Docker·Daemon ON·pool/RSS/CPU·복수Node replica exactly-once. 사용자 순서에 따라 수집 CPU/메모리 최적화는 Track1/2 뒤이며 Daemon OFF 방침을 유지한다. 리뷰어 미실행을 root 기존 위임의 새 승인 장벽으로 만들지 않는다.

## 핵심 source SHA256

| 경로 | SHA256 |
| --- | --- |
| backend/app/services/address_refresh.py | 9bd7052a38845035fab8dec28fcff28ccc5243679a692da9403d58125a54bff7 |
| backend/alembic/versions/0025_reverse_addresses.py | 52b52c28c19da21783e3453ea026e9486ebcb5545d160ced4f59ef102aed1128 |
| backend/app/schemas.py | 657bca9fe4a6d4e3278187b87e727d8690f74dffd3f8f2483d8d8034e4267710 |
| backend/app/dagster/address_refresh.py | b35d22481f934fd5167952bf209b845b4cd7ff1d398263a6990065ad2063940f |
| frontend/app/api/address-refresh/route.ts | 4dc74f8bea409f98606e0a99b9cc8be0be170d44d7dd1336857d7734bd84e5ca |
| frontend/components/address-refresh.tsx | c3b5296505c08808f10c77afdfb3d1961cfacfa0eeb33fd7ed92af872f6f5e44 |

## 최종 판정

**PASS / OPEN P0/P1/P2=0**, T86-B-P2-01 CLOSED 유지, T86-B-P2-02 CLOSED. 구체 재현에서 현재 소비자 선택범위와 같은 좌표 last-good 의미가 일치하고, 검토 범위에서 새 차단 결함을 발견하지 못했다. 기존 REQUEST_CHANGES 보고서는 그대로 보존한다.

## 실제 전달 요청 원문

~~~text
Transport86 formal FULL r3 독립 리뷰 부탁합니다. 불변 manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r3.json SHA2565effb1be7ca00fd6872f6dd1ef25cc9b9e7f79bae683c3b329d0369e7af92c87. base61a566dee0b1cc40f858652c0683883c26e56411→head1554783755ccf30be24bcafbab039322c6a685d3, WT/home/digitie/dev/kor-travel-transport-codex-reverse-address-20261018. Common522525aed3db934767c1c9e742b3bfc68e91679c. 본인r2 B P2 T86-B-P2-02 last_resolved_at를 Common40 join/currentcoords MAX로 수정했고 삭제/필터/이동 제외+같은좌표failed last-good 유지. 본인의 OPEN closure를 current consumer 전체base→155에서 직접 판단. exact CI두runSUCCESS(PR39094548318 backend849PASS2SKIP1603.62s), root22/Docker22/UI13/actualPG negativepositive drillPASS. 과거r1/r2 verdict와root실패기록보존, pin만아닌wholefeature/auth/schema/source/cursor/lease/native/DTO/UI/dependency등FULL. read-only immutableGit/ownsterilepurefixture만; other agents존재, source/index/branch수정/production/SSH/SDK/provider/DB/Docker/daemon없음. reviewer만의범위로root기존위임철회아님. peer새r3는둘final전열람금지. 요청전문/hash/time/tests/limits/concreteP0–P2/verdict를 /home/digitie/dev/reverse-address-transport-review-popper-r3.md 로raw저장/SHA보고. 적용AGENTS/runbook따라독립FULL로진행.
~~~

검토 종료 UTC: 2026-10-18T04:19:33.789857+00:00
