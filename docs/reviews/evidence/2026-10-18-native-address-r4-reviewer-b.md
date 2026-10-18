# Transport native idempotent submission — Popper formal FULL r4

판정: **CONDITIONAL / REQUEST_CHANGES — OPEN P0=0, P1=0, P2=1(공통 의존성)**.
앱 자체의 새 P0–P2는 찾지 못했지만 exact a68 pin의 PostgreSQL statement_timeout 소실을 열린 의존성으로 남긴다. 소비자 코드를 최종 SOURCE PASS로 확대하지 않는다. 운영 배포·provider·daemon 수용은 NOT_RUN이며 새 사용자 승인요건을 만들지 않는다.

## 불변 경계와 독립성

- manifest: /home/digitie/dev/reverse-address-transport-native-review-manifest-20261018-r4.json; 관찰 SHA256 **a18256ee4805fbccd362dbd907e1549a08f58981277f232a1525c4ea53fd0a3c**.
- base **61a566dee0b1cc40f858652c0683883c26e56411** → head **bb191137406b95a43f6ed8e477b35b786f88df0d**; Common **a68d0495acc38906c31b95b1d0db163bd8f96f5b**.
- 모든 manifest files의 Git blob SHA256을 대조해 불일치 0. base..head diff-check EXIT0.
- 초기 source 읽기는 앞선 Common 보고서 마감 직후, 소유 실행 fixture 시작 2026-10-18T05:14:43.309295+00:00; 보고서 확정 2026-10-18T05:17:12.965794+00:00 UTC.
- WSL Ubuntu-26.04, immutable Git object / Git archive와 소유 ext4 경로 **/home/digitie/dev/consumer-r4-popper-v3kdvqam**만 사용했다. shared source/index/branch/WIP를 수정하거나 checkout하지 않았다.
- 새 상대 소비자 r4 원문/모형은 읽거나 요청하지 않았다. 과거 본인 확정 FULL과 실제 byte 비교는 참고했고, 다른 앱 PASS로 이 앱 판정을 대신하지 않았다. 부모가 timeout finding의 존재를 알려준 사실과 본인의 실제 PG 재현을 구분한다.
- root/저자 validation: native_delay1 PASS, UI17 PASS; manifest 당시 full_python/remote_ci RUNNING, production NOT_RUN. 이것을 본인 실행이나 현재 CI SUCCESS로 세지 않는다.

## OPEN P2 — C41-B-P2-01 의존성

위치: 이 소비자 pyproject의 Common a68 고정 및 Common packages/py/kor-travel-common/src/kortravelcommon/dagster_webserver.py:216–231 (별도 create_engine → bound run SQL).

실패조건: 정식 PostgresRunStorage.optimize_for_webserver로 statement_timeout을 설정한 native webserver에서 launchIdempotentRun을 호출한다. 현재 별도 NullPool 연결은 URL/connect_timeout만 받고 native engine connect listener를 계승하지 않는다. authoritative run SELECT/UPDATE를 그 연결로 돌리는 a68 fix 때문에 native SQL의 기존 시간 예산이 사라진다.

본인 실제 .24/.25 + 소유 disposable PG에서 optimize_for_webserver(statement_timeout=321) 후 SHOW 결과는 outside **321ms → submission_lock 안 0 → outside 321ms**였다. 잠금 연결 소실 P1은 닫혔지만 잠금 대기/SQL 지연을 제한하는 native 계약은 보존되지 않는다. 서비스 PG/worker/provider는 사용하지 않았다. 원문 **/home/digitie/dev/common41-review-popper-r3.md**, SHA256 **6328cbc39d0c8e3e9860e4594e4df9028f8a51d72d7b5ed8cb99c46f3e4b8737**에 정확한 소유 fixture와 결과가 있다.

권고: native creator/listener/옵션을 계승하면서 원 pool을 점유하지 않는 연결을 사용한 공통 수정과 해당 pin 갱신을 별도 불변 대상으로 재검증한다. 부모는 새 89291f 제품을 알렸지만 이 보고서는 a68을 소급 교체하지 않는다.

## 전체 소비자 기능·연결 확인

- 전체 base..head 43파일/2419+/10-를 파일 목록·runtime diff·연결 코드로 검토했다. 1554783 본인 r3 FULL 이후 backend/app, migration0025, Compose는 byte 동일임을 직접 대조했다. 이전 source 지적을 pin 변경만 보고 닫지 않았다.
- 5종 source union: fuel/bus/ferry/rail/rest_area, lon124–132/lat33–43. ferry guideline 제외의 NULL 또는 admin_manual 허용을 유지한다. 동일 source selector가 page/retries/pending/summary/sample에 전달된다.
- **T86-B-P2-01 CLOSED 유지**: 실제 소비자 selector에서 legacy guideline은 provider 요청·sample·total에서 제외되고 기존 파생 행도 숨겨진다. admin_manual/NULL은 남는다. exact 제품 test 3개를 새 a68에서 다시 실행했다.
- **T86-B-P2-02 CLOSED 유지**: Common a68의 reverse_address.py는 522525a와 byte 동일하며 현재 source+같은 좌표 join MAX를 유지한다. 실제 legacy-only last_resolved_at=None 회귀를 새 pin에서 다시 실행했다. 같은 좌표 실패의 last-good 보존은 기존 본인 FULL과 공통 byte equality로 계승한다.
- migration0025는 별도 sidecar entries/control/인덱스만 생성하고 ALEMBIC_HEAD와 metadata가 정렬된다. 기존 source/fact/lineage 테이블에 rewrite 없음. schema/DTO/OpenAPI·Admin readonly GET와 token fail-closed 경계를 읽었다. 기존 API 전체 integration·PG DDL 실행은 이번에 반복하지 않았다.
- backend pyproject/uv.lock/health assertion의 a68가 일치한다. lock에서 Common과 backend 자신 외 dependency 변화가 없다. config address_batch1–500/timeout(0,10] 및 Compose의 동명 scalar 전달은 유지한다.
- 두 앱의 실제 BFF: session + durable session 인증, Origin 검사, JSON1024B·UUID 단일 key, lower UUID, fixed job/location/repository/force/tag를 확인했다. 임의 executionParams를 입력받지 않는다.
- POST의 prior가 terminal/queued/running이면 같은 요청 결과 재조회. prior NOT_STARTED는 active와 같은 run이거나 비어 있을 때만 native mutation으로 재제출한다. 다른 active는409다.
- module boolean은 단일 Node process 내 동시 진입만 막는다. 별도 replica의 전역 서로 다른 요청 admission/exactly-once를 보장하지 않는 문서 한계와 맞다. 같은 UUID native idempotence는 Common 구현에 의존한다.
- 새 mutation 미설치/GraphQL 오류/unknown/busy는502이며 기존 비멱등 launch로 fallback하지 않는다. UI는 timeout/409/502에서 UUID를 보존한다. terminal replay는 실패·취소·성공을 나눠 표시하고 늦은 GET200이 launchError를 지우지 않는다.
- 화면의 주소·provider·stale·last-good/다음일은 파생 DTO만 표시하며 KST를 명시한다. React text escaping을 사용한다. UI busy는 BFF/native 보호의 대체가 아니다.
- 공용 webserver opt-in entrypoint 선배포 후 Admin 배포 계약이다. 소비자 PR 자체가 Manager/shared webserver 기동을 바꾸거나 daemon을 시작하지 않는다.
- native delay fixture는 loopback opt-in에만 실행하고 전체 운영/provider/worker once proof라고 과장하지 않는다. 12초 지연/10초 upstream timeout 후 retry1run은 외부 좁은 시험이며 모든 경합 proof가 아니다.

## 본인 실행

1. 소유 Git archive + read-only frontend node_modules, sterile HOME/TMPDIR/PATH/CI 환경에서 actual route/scope/origin/NextRequest를 사용했다. 제품 Vitest **12** + 본인 **10** = **22 PASS** (588ms).
   - 본인 cases: prior NOT_STARTED+다른 active 거절, active 조회에서 이전행 부재 시 동일 UUID 복구, native busy/error 502/redaction 뒤 replay 재진입, prior QUEUED/STARTING/STARTED/CANCELING 새 launch0, GraphQL error/과대131073B응답 후 진입 해제, 과대1100B요청 upstream0, uppercase UUID의 prior/launch/tag lower 결박.
   - fetch/auth/session 대역이므로 실제 암호/쿠키/HTTP/Next server/browser/native worker proof는 아니다. 같은 제품 모형의 결과를 복사한 것이 아니라 소유 검사 파일의 assertion을 실행했다.
2. exact 소비자 test_address_refresh.py + actual Common a68 source 및 실제 GraphQL create_schema/validate: **5 PASS** / 4.80s.
   - Transport: 실제5종 모델 원천보존1 + legacy/admin_manual/NULL admission·기존파생숨김·legacy-only MAX회귀3 + native GraphQL문서1. API test_settings fixture가 필요한 HTTP통합1개는 명시 deselect했다(1 deselected).
   - -I -B / PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 / --noconftest -c /dev/null -p no:cacheprovider, settings _env_file=None. 자신 temp SQLite만 사용했고 기존 repo conftest/private env/PG/실제 provider를 열지 않았다.
3. Common reverse_address.py/address_providers.py/address_dagster.py/http_health.py/build_bytecode.py를 a68 vs 기존522525a Git object로 비교: 전부 byte 동일. native 제출 모듈만의 새 정책 위험은 별도 P2로 남겼다.
4. diff-check EXIT0, manifest 전체 file SHA 불일치0. 제품/테스트 실패 없음. 초기 소유 경로 목록 tool에서 파일을 directory로 순회해 NotADirectoryError1회가 있었고 테스트 실행 전 도구 준비 오류였으며, directory 검사로 정정했다.

## 소유 증거

- /home/digitie/dev/consumer-r4-popper-v3kdvqam/transport/app/api/address-refresh/popper.test.ts: SHA256 **a6b73bd8cdb21adc651105ba235da6ff637d191f681faf027e93343479433328**.
- /home/digitie/dev/consumer-r4-popper-v3kdvqam/transport/vitest.stdout.txt: SHA256 **37132586264063a322b002818896a55e183a916eaa8dc9d893dce7dbe5864cdf**.
- /home/digitie/dev/consumer-r4-popper-v3kdvqam/transport-py/pytest.stdout.txt: SHA256 **70c63217e3e0549cbe4a5607a1aae34d05661debd348a31d1f8ff432588a41c0**.

## 한계

실제 PostgreSQL 소비자 migration/행락/lease·multi-process BFF·소비자 full suite·fresh image/wheel/ARM 빌드·브라우저·운영/실 provider/daemon/실 worker는 이번 소비자 리뷰에서 NOT_RUN이다. Common 소유 PG 실험은 독립 공통 정책 재현이며 소비자 운영 proof가 아니다. 외부 manifest 당시 CI RUNNING을 SUCCESS로 승격하지 않았다. 별도 Common/Weather/Transport 리뷰와 운영 적용은 서로 대체하지 않는다. 실제 native run eventlog 실패시도 한계와 source 실패 이력은 기존 Common 보고서 및 guide 그대로 보존한다.

## 실제 전달 요청 원문

A 최종 Common41 docs/head3093d2169e2ad9a4c536ed457d1f6e61918f73a0 제품a68 동일 확정. 제품판정 후 docs delta 정확성도 확인 부탁드립니다(작성자 handoff는 본인독립판정 고정 후). 운영NOT_RUN/eventlog attempt한계 및 기존 실패 보존. 완료 후 Weather115/Transport86 FULL r4 소비자 리뷰 요청: manifests /home/digitie/dev/reverse-address-weather-native-review-manifest-20261018-r4.json SHA2af750b4d7690cd4ba9865625fd6b78ec03e413a3b5b046a7970a5b690475093, transport SHAa18256ee4805fbccd362dbd907e1549a08f58981277f232a1525c4ea53fd0a3c. 두앱각UI17/native delay1PASS, full/CI진행.

이후 전달:

C 독립 리뷰에서 a68 새로운 statement_timeout 소실 P2 확인해 A 수정 요청. 본인 a68 보고서는 현재 범위 그대로 마감 보존하고 새제품 전까지 소비자 r4 FULL 리뷰로 전환해 주세요. 핵심: optimized native engine의 timeout과 별도NullPool lock연결 설정 차이. peer보고서 원문은 읽지 말고 필요시 독립 재현. 새 pin 나오면 최종delta 다시 요청.
