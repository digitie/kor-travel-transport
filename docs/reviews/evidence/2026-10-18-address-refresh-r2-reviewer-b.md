# Transport86 formal FULL post-fix r2 — Popper 독립 리뷰

**판정: REQUEST_CHANGES. OPEN P0=0 / P1=0 / P2=1.**
원 T86-B-P2-01 admission 문제는 CLOSED다. 별도 집계 반례 T86-B-P2-02가 새로 남았다. 실제 운영 미검증과 SOURCE PASS를 혼동하지 않으며 root의 기존 위임을 철회하거나 추가 사용자 승인 요건으로 바꾸지 않는다.

## 대상과 격리

- Base: 61a566dee0b1cc40f858652c0683883c26e56411
- Exact head: 8c89e1a72d92b54865bb0f2db553c1c2cfe17561
- 이전 본인 head: f8e5dd06f8bfe478fdb57785e70b2304958333ad
- Common pin: c067a7f6a11b106931a73cd7465503d90e54d976
- Manifest: /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r2.json
- 관찰 SHA256: 96463ba6d27c80a69cb2a3e43db907be47ce809d13301f3ba22f41bf85c3f527
- 이전 본인 r1 원문 SHA256: 3cf97813be890bd0030d78508d56ccd0ecb95f6bce0adc9033e508f8133a4132. 원본을 수정하지 않았고 Git archive의 복사본/manifest가 로컬 원본과 byte 동일함을 확인했다.
- 전체 base→head 33파일. path+NUL+SHA256+LF 연결 목록 SHA256: b888bca0d249c46c4c759ddae2a26fb58007b681d65e736c6358189853b4f6c9.
- r1 전체 검토를 계승하고 이후9파일 delta와 연결 Common/소비자·API·UI·schema·설정·문서를 다시 읽었다. 제품의 실제 함수 변경은 address_source 하나다. 다른 service 함수 AST, API/BFF/component/migration/pin/config는 r1과 동일하다.
- CLAUDE/AGENTS/SKILL/runbook의 읽기 전용·한국어·독립성 기준을 유지했다. immutable Git blob을 소유 임시 src에 추출하고 sterile env, -I/-B, --noconftest, no cacheprovider로 실행했다. 실제 env/비밀/SDK/PG/provider/SSH/Docker/Daemon 접근·조작, source/index/branch/WIP 변경 0. 새 상대 r2 원문은 읽거나 요청하지 않았다.
- 시작 UTC는 수집하지 않았다. manifest created_utc는 내 시작 시각이 아니다. 종료 UTC는 아래에 기록한다.

## 원 T86-B-P2-01 — CLOSED

위치: backend/app/services/address_refresh.py:33–47.

FerryPort branch에 (location_source IS NULL OR location_source != 'data_go_kr_port_guideline')가 AND로 추가됐다. SQL의 NULL 비교에서 단순 !=만 사용하지 않아 출처 미지정의 유효 좌표를 빠뜨리지 않는다. 나머지 네 종류의 union 선택은 동일하다. 기존 숫자 범위 조건도 보존한다.

본인 exact8c/Commonc067 소유 SQLite 검증:
- legacy guideline, admin_manual, NULL, komsa_port_call, vworld_place, kakao_place, 빈 문자열의 FerryPort7행을 만들었다. NULL과 나머지 기존 허용 provenance6행은 page에 포함하고 legacy1행만 제외한다.
- 일반 page 및 force/cycle/now 5인자 page 양쪽을 확인하고 실제 source SELECT를 PostgreSQL dialect로 compile해 IS NULL OR != 조건을 확인했다. 실제 PG 접속은 하지 않았다.
- 정확 run_address_refresh에서 resolver6회/허용키6개만 처리했다. legacy 신규 sidecar는 생기지 않는다.
- 원천 FerryPort 전체 열을 갱신 전후 비교해 동일했다(raw_item_json/관리자 흔적/출처/좌표 포함).
- 이전 admission으로 생성된 legacy 정상 sidecar를 실제 store.claim/prepare/save로 만들어 두어도 sample/items에 나오지 않고 total/failed의 현재 source 집계에는 포함되지 않는다. run 후 기존 legacy sidecar도 byte 의미상 동일한 row로 보존된다.
- legacy 오류와 유효 manual 오류를 함께 만들면 retries(limit1)가 유효 manual을 선택하고 pending_failures/failed에서 legacy를 제외한다.
- 유효 source를 없애 legacy만 남기면 retry=[], pending_failures=false, total/failed/items=0/0/[]다. 기존 manual cycle은 빈 배치에서 cleanup되고 provider 호출0·remaining0·has_work(auto=false)=false로 끝난다.

따라서 원 지적의 provider admission·주소 정상 게시 오류는 해결됐다. 아래 last_resolved_at은 원 주소 표본과 구분한 새 통계 경계 지적이다.

## T86-B-P2-02 — 제외된 source가 최근 정상 확인 시각 집계에 남음

**위치:**
- Common c067 packages/py/kor-travel-common/src/kortravelcommon/reverse_address.py:551–555, 560
- Transport backend/app/services/address_refresh.py:57–60 (source.summary 그대로 반환)
- packages/kor-travel-transport-admin/frontend/components/address-refresh.tsx:70 (최근 정상 확인 표시)
- 관련 소비 계약 docs/reverse-address-refresh.md:82–83 (legacy를 갱신·집계·최근 결과에서 제외)

**실패 조건:** 과거에 legacy guideline 항구로 저장된 정상 sidecar만 있고, 현재 source selection에는 그 항구를 제외하여 유효 대상이0개다.

Common summary의 total/due/failed는 현재 self.source join을 사용하지만 last_resolved_at만 provider_id 전체 entries의 MAX(resolved_at)다. source/좌표 일치 조건이 없다. Transport가 그대로 노출하므로 제외된 항구의 과거 결과가 “최근 정상 확인” 시각의 근거가 된다. 기존 row 보존과 현재 집계 제외는 서로 다른 계약이다. row를 지우지 않고도 집계는 제외해야 한다.

**본인 실제 반례:**
1. 정확8c 모델로 다섯 source 테이블과 새 두 테이블을 소유 SQLite에 생성했다.
2. FerryPort id1, location_source='data_go_kr_port_guideline', 범위 안 좌표127.01/37.01만 남겼다.
3. 정확 Common store.claim/prepare/save를 사용해 과거 정상 파생 결과/resolved_at=2026-10-18T00:00:00+00:00을 저장하고 cycle을 완료·release했다. 실제 provider 호출0이다.
4. 정확 소비자의 address_source(settings).summary()를 실행했다.

관찰 출력:
    total=0
    due=0
    failed=0
    items=[]
    last_resolved_at="2026-10-18T00:00:00+00:00"

유효 대상이나 표시 가능한 정상 결과가 전혀 없는데 최근 정상 확인 날짜가 남는다. 이는 새 문서의 legacy 집계 제외와 불일치한다. 원천/기존 sidecar mutation은 없으며 실제 운영에 이런 row가 있다고 관찰한 주장은 하지 않는다. 반례의 assert는 “잘못된 날짜가 실제 남음”을 확인하므로 해당 시험의 PASS를 제품 PASS로 계산하지 않는다.

**최소 권고:** 공통 summary의 최근 정상 시각도 현재 source와 유효 좌표 일치 범위를 기준으로 MAX한다. source/row 삭제나 global cache 파괴는 필요하지 않다. legacy·삭제 source·좌표 불일치 결과만 있는 경우 last=None, 현재 유효 source의 정상/마지막 정상 확인일은 유지되는 양성/음성 회귀를 함께 확인한다. 같은 Common 메서드의 다른 소비자에도 영향을 미치므로 공통 쪽에서 최소 수정하고 pin/CI/독립 검토를 다시 결박하는 것이 적절하다. 현재 exact8c의 이 지적은 OPEN으로 보존한다.

## 직접 실행 정산

소유 fixture 묶음: **8 passed / 1.06초 / exit0**.
- 본인 positive4개: NULL/provenance page+PG compile, actual run/source 전체행 보존, 옛 sidecar 숨김/보존, retry/pending/cleanup.
- 고정 source의 기존/추가 pure 시험3개: 원천보존과 legacy 두 회귀.
- 별도 반례 확인1개: 위 잘못된 last_resolved_at을 assert로 재현. 이것은 결함 존재 확인이며 source PASS 근거가 아니다.

실제 provider·외부 network·SDK·PG·브라우저 실행0. fixture는 임시 디렉터리 삭제로 종료했다. 이번 새 묶음에서 fixture 실행 실패는 없었다. r1의 최초6P/3자체 fixtureF→해당3P 기록은 기존 원문에 그대로 남아 있다.

## 전체 base→head 연결과 새 회귀 탐색

- 주소 엔진 연결의 page/retries/필수 pending_failures, force 및 batch·timeout, consumer context의 finally dispose가 보존됐다. SQL OR 조건이 source 선택에만 추가되어 트랜잭션·lease·worker fencing·재시도 순서를 재구현하지 않는다.
- AUTO=false 수동 실패/backoff/신규 cursor 앞 대상/삭제 실패 cleanup과 만료 worker의 늦은 save 차단은 Common c067/r1 검증과 source 동일성으로 계승한다. 이번 retry/legacy cleanup fixture는 해당 좁은 연결을 새로 실행했다.
- migration0025/down_revision0024와 startup ALEMBIC_HEAD, metadata/schema/DTO/OpenAPI, 모델의 PK/source lineage, Common pin/extra/lock, provider 직접 사용/설정/Compose는 r1과 byte 동일하다. 원천/관리자 좌표/fact·일반 map/export를 바꾸지 않는다.
- r1의 실제 migration SQLite/PG DDL compile·Pydantic/OpenAPI 일치·다섯 종류 id 충돌 방지·resource dispose 결과를 계승하며 이번 전체 PG/migration을 재실행했다고 쓰지 않는다.
- API 관리자 sync GET의 token fail-closed/threadpool 및 BFF session/Origin·고정 location/job/force/tags·본문/응답 상한·deadline은 동일하다. 새 endpoint 또는 client 제공 job 범위를 추가하지 않았다.
- BFF의 단일 Node check/set/finally 가드와 replay FAILURE/CANCELED/SUCCESS/QUEUED 구분, loadError/launchError 분리도 byte 동일하다. r1 VM43조건을 새로 실행한 수치로 쓰지 않는다. 여러 replica/재시작/UNKNOWN 뒤 늦은 server 확정까지 전역 exactly-once라는 주장은 여전히 없다.
- 최종 주소는 Admin/API의 파생 결과이고 일반 locations/map 원천 필드를 치환하지 않는 범위가 유지된다.
- A r1 P3의 viewport 수량 문구는 “두 화면을 합해 앱13”으로 바로잡혔다. r1 양쪽 원문/manifest의 byte/hash와 당시 REQUEST_CHANGES가 보존됐다. 새 상대 결과는 포함하지 않는다.
- 사용자의 Track1/2 우선·후속 CPU/메모리 최적화·Daemon OFF를 새 검증/배포 완료로 확대하지 않았다.
- base..head git diff --check를 직접 실행해 exit0을 확인했다.

## 외부 증거·CI·미실행 범위

공개 GH를 read-only 조회해 exact8c의 pull_request39092813701 completed/success를 확인했다. push39092810095는 조회 당시 in_progress/conclusion없음이다. 후자는 PASS에 집계하지 않으며 root가 merge 전에 별도 확인할 항목이다. 이 리뷰는 새 CI를 실행하지 않았다.

848P2S/910.63초·frontend/Admin SUCCESS, current8c WSL21/Docker21/실제PGdrill/fresh loopback UI13은 root manifest의 증거다. 본인이 재실행한 것으로 합산하지 않았다. 이전6a fullDocker835/13은 현재8c full 검증이 아니다. root의 UI26 역사 증거도 현재 backend full 검증을 대체하지 않는다.

공개 legacy 검증 artifact SHA256 ab836d6d3afad71660aef86ff27fbeb5bd18a0bb986922965b4646e9fbcaa6bc 및 역사 fullDocker artifact SHA256 8d068bd19fe3e9ddef6d0f9ae81a1f29b3a93c73feac49862a0a7b43afd84465를 직접 확인했다. 각 scope/head/pin이 구분되어 있었다. 실제 PG raw log나 env/private 내용을 읽지 않았다.

운영 migration/provider 권한/응답/native배포·수집 완주·운영 UI/CPU/RSS, 실제 DB 경합·Dagster event/run은 본인 NOT_RUN이다. SOURCE PASS와 이런 운영 수용을 구분한다. root의 기존 권한을 새 승인 요건으로 바꾸지 않는다.

## 주요 hash

- address_refresh.py: 9bd7052a38845035fab8dec28fcff28ccc5243679a692da9403d58125a54bff7
- tests/test_address_refresh.py: b23047e5085c2019274eae57fc7bed86e98f08aa84308b3ae6222e4cdb678cc2
- guide: 7d0ebf7e054388fc282e3b8fb70105ece6b80e608b18e4dde522cb3b1a4ea551

## 실제 전달받은 요청 원문

parent NEW_TASK payload를 그대로 보존한다. 메시지 자체의 UTC timestamp는 제공되지 않았다.

```text
Transport86 formal FULL post-fix r2를 독립 Popper/Backend·PostgreSQL·ops·failure recovery 렌즈로 수행하세요. 목적은 통과가 아니라 결함 발견이며 애매하면 지적. 정확히 같은 immutable manifest /home/digitie/dev/reverse-address-transport-review-manifest-20261018-r2.json SHA256 96463ba6d27c80a69cb2a3e43db907be47ce809d13301f3ba22f41bf85c3f527. base61a566dee0b1cc40f858652c0683883c26e56411 → head8c89e1a72d92b54865bb0f2db553c1c2cfe17561, WT /home/digitie/dev/kor-travel-transport-codex-reverse-address-20261018. 자신의 원 r1 REQUEST_CHANGES/P2 T86-B-P2-01는 그대로 보존하고 이번 legacy ferry admission 수정의 NULL/admin_manual 유지·page/retry/summary/sample 공통 경계·이전 파생 결과 숨김·source 불변을 재검증해 CLOSED/OPEN 근거를 명시하세요. A P3 guide count도정정. 전체 base→head delta에서 새 회귀/SQL NULL/자원해제/스케줄·lease·timeout·idempotency/schema/config/security 문제를 의심. exact-head PR CI39092813701 SUCCESS, PostgreSQL848P2S/910.63초, frontend/Admin SUCCESS; duplicate push39092810095는 아직 진행이며 PASS 아님. current8c focusedWSL21/Docker21, 실제PGdrill, freshAPI/native loopbackUI13 PASS, evidence/manifest 한계 확인. 이전6a fullDocker835/13은8c full 검증이 아님. source/API/UI/migration/shared dependency 전체를 검토하되 production/SSH/provider/daemon/Docker 조작과 env/비밀 접근은 금지. immutable Git object와 자신 소유 temp/fixture만 read-only 검증, source/index/branch 편집 금지. 다른 에이전트도 있으니 편집/되돌림 금지. 새 상대 r2 결과는 둘 다 최종 확정 전 읽거나 요청하지 마세요. 기존 확정 r1/common/weather history는 참고 가능. 실제 전달된 이 요청 원문, 관찰한 manifest hash/base/head, 시각/격리, 검사/실패/미실행 한계, findings file:line/구체재현/P0-P2와 original P2 closure근거를 보존한 최종 원문을 /home/digitie/dev/reverse-address-transport-review-popper-r2.md 에 작성하고 SHA256과 verdict/OPEN P0/P1/P2를 보고하세요. 실제 운영 미검증과 SOURCE PASS를 구분하고 root 기존 위임을 새 승인요건으로 바꾸지 마세요.
```

보고서 종료 UTC: 2026-10-18T03:34:45.038403+00:00
