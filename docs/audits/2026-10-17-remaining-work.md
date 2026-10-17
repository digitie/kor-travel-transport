# Transport 남은 작업 감사 — 2026-10-17

## 판단 기준

소스 정본은 main `d1593ecc26eb352b12603e95e56061431527f286`이다. [PR84](https://github.com/digitie/kor-travel-transport/pull/84)는 2026-10-17 11:03:25 UTC에 머지됐다. 제품 `af8a9a2`, 최종 문서 `06d025a`와 main의 tree는 같다. PR84의 backend/frontend/admin 6 SUCCESS·live 2 SKIP와 main CI run `39027238190` SUCCESS를 공개 GH에서 확인했다. 이 감사는 소스·GH·root 공개 safe 증거만 읽었으며 운영 접속·테스트 재실행·배포를 수행하지 않았다.

root의 최신 운영 관측은 **2026-10-17 11:58:07 UTC**다. 전체 77개 중 16 running, running 중 14 healthy·2 noHC·0 unhealthy이며 공용 daemon은 OFF다. Transport backend/frontend HC30초, admin/gateway45초, code-server90초다. 이 상태 조회는 수집 부하 CPU/RSS·provider 성공·DB 정합성 검증이 아니다. 사용자 재개 지시 전에는 daemon을 시작하지 않는다.

Transport appdir Git HEAD는 `06d025a`지만 backend runtime의 RELEASE_SHA는 `40f6349`, native API/CS image의 revision은 `ac57b56`로 남아 있다. 기존 PR83 native overlay의 엄밀한 파일/패키지 검증과 별도로 **메타데이터 정산이 남은 상태**다. 낡은 RELEASE_SHA만으로 실제 코드 미배포를 단정하지 않으며, 표시만 최신으로 덮어 실제 소스 정합성을 위장해서도 안 된다.

아래 파일·행 근거는 특별한 표시가 없으면 위 main 스냅샷 기준이다. 정본 백로그는 [tasks](../tasks.md), 최신 요약은 [resume](../resume.md), 실패·진행 이력은 [journal](../journal.md)이다.

## 완료 범위와 완료로 세지 않은 범위

| 항목 | 확인된 완료 | 남은 범위 |
| --- | --- | --- |
| Track1 / T-045 | [PR76](https://github.com/digitie/kor-travel-transport/pull/76) `eb40e3b` 머지. Transport는 Geo를 호출하지 않고 Geo 유도 행정코드/PNU/version을 저장하지 않는다는 소스 근거를 문서화 | Transport token/regeo job 신규 구현은 불필요. `tasks-done.md:24`의 머지 SHA 후속 기입만 낡은 문서 잔여 |
| PR84 / T-TRN-01 이번 범위 | 필수 --host·Manager hosts.addr 효과·prod 명명, 독립 A/C 리뷰, WSL95 PASS, 현재 archive의 로컬 Docker95 PASS/0 SKIP. root 실제 승인0/비로컬2/env없음2·동일 env0600·tracked source 적용·UI34 PASS | 전체 backend/frontend 공식 ARM build/recreate·첫 전체 cutover를 실행한 것은 아님. 전체 task는 unchecked 유지 |
| T-TRN-02 | [PR78](https://github.com/digitie/kor-travel-transport/pull/78)의 공개 Dagster URL build arg 전달 source, PR84의 prod env 명명, 현재 운영 UI 링크 포함 34개 기준 수용 | 새 env로 만든 **새 bundle**의 값 재현, 호스트별 env 전체 정리. 현재 컨테이너/번들 재사용과 구분 |
| 점검 CPU / PR82·83 | [PR82](https://github.com/digitie/kor-travel-transport/pull/82) EXISTS, [PR83](https://github.com/digitie/kor-travel-transport/pull/83) Common c485·사전 컴파일·경량 HTTP·주기3배가 main에 머지. root native 적용·기존 UI34·제한된 idle CPU 관측 존재 | 공식 현재 Dockerfile의 clean ARM build/Chromium/provider smoke와 수집 부하 CPU/RSS는 별도. 점검 주기 변경을 수집 cron3배로 확대하지 않음 |
| 수집 저장·복구 | [PR67](https://github.com/digitie/kor-travel-transport/pull/67) owner/heartbeat/fence·회수·인프라 retry, [PR74](https://github.com/digitie/kor-travel-transport/pull/74) 저장 일시 오류 1회 retry·안전한 실패 원인, [PR75](https://github.com/digitie/kor-travel-transport/pull/75) 유가 bulk upsert가 main에 존재 | 현재 환경의 수집 완주·강제 중단 없이 복구·재시도·장기 메모리 수용은 미확인. 기존 구현을 새 기능으로 중복 작성하지 않음 |

Track1의 상세 책임 경계는 [data-model의 Geo 미사용 절](../architecture/data-model.md), `docs/architecture/data-model.md:173–200`, `docs/resume.md:53–58`이다. Map이 export 좌표를 reverse-geocode하는 동작은 Map 소유이며 Transport 변경으로 확대하지 않는다.

## 우선순위와 최소 다음 행동

| 우선순위 | 진짜 잔여 | 현재 단계·선행 조건 | 최소 다음 행동·필요 실측 | 근거 |
| --- | --- | --- | --- | --- |
| P0 유지 | daemon OFF·기존 데이터/실패 이력 보호 | 사용자 일시중지 유지. 이번 감사/문서 PR은 실행 재개 권한이 아님 | source 검증과 오프라인 준비만 가능. 자동 재개·job 발행·기존 queued 취소 금지 | root 11:58:07 safe 관측; runbook 첫 계약 |
| P1 | T-TRN-01/02/04 전체 배포 경로·ARM/browser 수용 | PR84의 최소 수용은 끝남. 전체 pipeline을 완료했다고 표시할 근거는 없음 | 새 source/parent/metadata 정합성부터 확인하고 공식 ARM 후보·Chromium offline smoke·새 URL bundle을 검증. provider 제한·공용 plane·worker drain을 보존한 별도 운영 창에서 전체 전환 수용 | `docs/tasks.md:130–171,196–207`; `backend/Dockerfile:1–42`; `docs/runbooks/deployment.md:659–676` |
| P1 | T-TRN-05 메모리/swap 제한 **source 구현** | 현재 canonical shared/admin Compose에 mem_limit/memswap_limit가 없음. 기존 운영값은 이 사실만으로 추정 불가 | 설계의 backend0.8g/CS1g·나머지 합0.3g 범위를 검토하고 frontend/admin/gateway 분배 근거 확보→동등 swap 제한 회귀→2인 리뷰. 이후 승인된 Opinet 실행 포함 창의 peak RSS/OOM 확인 | `docs/tasks.md:208–219`; 두 canonical Compose |
| P1 | collector CPU·메모리·실패 안정성 실환경 수용 | 저장/recovery source는 이미 구현됨. 현재 OFF라 최신 수집 완주 수용은 미실행 | 재개 승인 뒤 동일 job/자료량으로 수집·저장 시간을 분리하고 peak RSS, 호출 수, 오류 분류, DB retry1회, owner 늦은 쓰기 거절·부분 성공 보존을 확인. provider 재호출 없이 저장만 retry되는지 우선 확인 | `transport_collection.py:426–505,881–982`; `dagster/recovery.py:166–227`; `definitions.py:167–196,566–577` |
| P1/P2 | provider 인증/영구 파싱 실패의 장기 backoff/fail-stop | quota backoff와 일시 DB retry는 존재하지만 다른 종류의 장기 정책은 백로그 | 401/403·quota·일시 transport/DB·영구 schema 오류를 분류한 정책/재시작 회귀부터 설계. 단순 timeout 증가나 무제한 retry 금지 | `docs/tasks.md:236–244`; config timeout/backoff 값 |
| P2 | PR81의 공항/고속도로 시작 충돌 분산 | 현재 두 schedule은 모두 */5. PR81은 열린 draft·DIRTY이며 오래된 Common/HC와 얽힘 | 고유 phase1/3 변경만 최신 main 기준으로 재정산·2인 검토. c485·현재 strict HC·90/360초·env.prod를 보존. 수집 재개 승인이 나기 전에는 cron 실적용/발행 없음 | [PR81](https://github.com/digitie/kor-travel-transport/pull/81); `definitions.py:594–595` |
| P2 | 유가 지역 분산·영속 체크포인트·bounded memory | 아직 구현되지 않은 별도 기능. provider는 전국 결과를 한 번에 돌려주며 현재 fuel cron은8시간 | provider의 지역별 public 수집 계약/처리량 먼저 확인→영속 next_allowed/예약·체크포인트·늦은 worker fencing 설계. 고정 시계/난수·PostgreSQL 동시 예약 시험 후 제한 적용 | `docs/tasks.md:76–91`; [유가 분산 설계](../plans/fuel-regional-scheduling.md):33–85 |
| P2 | API/통계 냉·온 지연·큰 응답 동시성·남은 deadline 경계 | 일부 SQL/index/cache·cancel/슬롯 반환은 이미 존재. 문서 목표1초/3초와 실제 부하 수용은 별도 | 같은 데이터·응답 bytes·동시성으로 DB/직렬화/전송/프록시 시간을 분리하고 p95 확인. 만료 예산의 handler 진입 경계도 회귀로 확인. unbounded JSON 계약/timeout만 바꾸지 않음 | `docs/tasks.md:13–41,66–70,238–244`; `main.py:247–325` |
| P2 | 실제 provider/전국 데이터 완전성 | 과거 항구607·터미널649 미좌표와 배편346/749는 **9월 기준**이며 현재 수치 아님 | 다음 승인된 자연 run의 호출280상한·보류/실패·오늘 출발 항구/좌표 범위를 fresh 비교. 공식 시설 교차표·실제 마커 클릭 검증. OFF 상태에서 수집을 임의 발행하지 않음 | `docs/tasks.md:43–64,270–286` |
| P3 | T-TRN-03a 정책 문서 정합·03b legacy M 삭제 | 03a는 문서 잔여. 03b는 배포 수용 전까지 보존할 안전 자산 | 소유자 결정과 현재 운영 경계를 반영해 금지 문구만 먼저 정산할 수 있음. M6개 삭제·n150 해체·DB/이미지 정리는 전체 수용/백업/복구 확인 전 진행하지 않음 | `docs/tasks.md:172–195`; `docs/runbooks/deployment.md:678–681` |
| P3 | 추가 UI/보안/관측 백로그 | 브랜드 아이콘·교통/유가 map view·combobox·타일 회복/301역 복합 이벤트, Next/sharp 의존 영향 검토 등이 남음 | 사용자 우선순위별 별도 기능 단위로 처리. 기존 UI34 수용을 이 모든 복합 조합·새 공급자 수용으로 확대하지 않음 | `docs/tasks.md:93–108,234–235,297–314` |

**수집 메모리의 구체적 관찰점:** `_store_fuel_snapshot`은 DB 문장 크기를 주유소500/유가2000으로 제한하지만, 전체 provider snapshot·station_rows·station_prices·price_rows와 list 변환은 스냅샷 크기에 비례해 상주한다(`transport_collection.py:910–976`). 이것을 memory leak이라고 단정할 실측은 없다. 저장 phase의 자료량별 peak RSS·JSON 중복/객체 크기를 먼저 재고, 지역 분할 시 원본/읽기 모델/성공 상태의 원자성(`:901–903`)을 깨지 않도록 해야 한다.

기존 회수기는 metadata 조회 실패를 worker 사망으로 처리하지 않고 tick을 중단한다(`dagster/recovery.py:193–201`). provider 실패를 전체 infrastructure retry로 확대하지 않는 현재 job 분류도 보존한다. [복구 runbook](../runbooks/dagster-recovery.md)을 구현되지 않은 새 reaper로 오인하지 않는다.

## 열린 PR 3개의 정확한 의미

| PR | 현재 공개 상태 | 감사 판단 |
| --- | --- | --- |
| [81](https://github.com/digitie/kor-travel-transport/pull/81) `027ad551` | draft, main 비조상, DIRTY. 해당 옛 HEAD CI backend/frontend/admin3 SUCCESS·live1 SKIP(10월15일) | phase 변경은 main에 없음. 현재 main과 비교하면 Common41b/옛 HC/옛 env명이 섞여 있으므로 기존 green을 최신 main 수용으로 세거나 branch를 무검토 통합하지 않음 |
| [38](https://github.com/digitie/kor-travel-transport/pull/38) `671397e7` | draft, main 비조상. 옛 HEAD CI6 SUCCESS·live2 SKIP(9월23일). 최초 mergeability 조회 UNKNOWN, 후속 공개 GH 조회 CONFLICTING | 0011 migration은 main과 바이트 동일하고 rest-area 모델/API/job이 이미 존재함. UI 밀도 등 고유 차이는 최신 main 대조 후 정리/종결할 대상이며 feature 전체 중복 재구현 대상이 아님. 전체가 이미 머지됐다고도 단정하지 않음 |
| [31](https://github.com/digitie/kor-travel-transport/pull/31) `6b727062` | draft, main 비조상. 옛 backend/frontend4 SUCCESS·live2 FAILURE(9월20일) | 두 research 문서는 main에 없음. 남길 조사 내용과 오래된 config/핀 변경을 분리해 최신 사실로 검토할 잔여. 옛 live 실패를 현재 runtime 장애로 해석하거나 재시도로 지우지 않음 |

Manager530/531·Common38의 최신 union/review/native 차이는 root 공통 dependency 감사가 정본이다. Transport84는 Manager530의 hosts.addr 제품만 기존 RC에 적용한 실제 CLI 수용과 **미머지 PR530**을 구분한다. 후속 clean 설치 재현에는 정식 merged release 정합이 필요하지만, 이번 문서 작업이 다른 저장소 PR을 머지하거나 설치하지 않는다.

## 낡은 체크박스와 실제 미완료의 구분

- `tasks.md:226–227`의 최초 통합 수집/연구 착수, `:248–253`의 공용 DB·분리 job·REST 전부는 현재 구현/다수 머지 뒤의 오래된 묶음 표현이다. source 존재와 최신 운영 데이터·실환경 수용을 분리해 정산해야 하며 새로 전부 구현할 일이 아니다.
- `tasks.md:327`의 PR44 머지 대기는 낡았다(PR44는9월28일 머지). T-043의72시간 뒤 정리·백업 용량·prewarm까지 완료했다는 증거는 이 감사에 없으므로 나머지를 일괄 체크하지 않는다.
- `resume.md:65–75`의 PR미생성/미배포 표현은 현재 PR73·74가 머지된 사실과 다르다. PR75의 bulk upsert도 머지돼 있으며 다시 구현할 일이 아니다. 다만 각 provider의 최신 자연 run 성공·phase별 시간은 별도 운영 증거가 필요하다.
- `tasks.md:283–286`의 Opinet39e7 핀/30초 전달 문구는 source 기준 낡았다. 현재 pyproject 핀은4654310, config와 두 env 예제 timeout은60000이다. **실제 private env 값은 읽지 않았으므로 운영 timeout까지 최신이라고 주장하지 않는다.**
- `tasks.md:266–268`의 `.env.example` ferry7 vs prod예제9 불일치는 현재도 남아 있어 낡은 항목으로 버리면 안 된다. 반면 현재 code/API의 날짜 계약까지 바꿀 권한을 뜻하지 않는다.
- `tasks.md:315–317`의 versioned release/atomic switch·stale middleware 보호는 전체 PR84 수용으로 닫히지 않는다. root는 이번에 위험한 rsync --delete 대신 tracked Git 전진으로 `.git`·backups·비추적 파일을 보존했다.
- PR82·83 문서의 당시 native/live/CPU NOT_RUN은 과거 이력이다. root의 이후 제한된 native/idle/UI 증거를 최신 요약에 연결하되 당시 실패와 공식 ARM/수집 부하 미실행 범위를 삭제하지 않는다.

## 실측 증거의 시점과 한계

| 공개 safe 증거(root 수행, 저장소 외부 보관) | 시점·확인 내용 | 확대하면 안 되는 주장 |
| --- | --- | --- |
| `transport84-ui34-root-bound-r3-20261017.safe.json` | 10월17일10:32:03–31 UTC,34 PASS/0 FAIL. 전후 native SHA 동일, daemon OFF | 기존 runtime을 이용한 UI34가 새 ARM image·새 bundle/수집 성공을 입증하지 않음. r1/r2 각31P3F namespace 실패 보존 |
| `transport84-host-gate-closure-root-r1-20261017.safe.json` | approved0/nonlocal2/missingenv2, 전역 CLI 준비 뒤 효과 확인; 77/16·env 동일·build/recreate0 | 최초 CLI 부재 거절 보존. 전역 CLI 단독/marker만으로 전체 설치/이미지 출처를 판정하지 않음 |
| `remaining-three-projects-native-read-root-r1-20261017.safe.json` | 10월17일11:58:07 UTC,77/16,14healthy2noHC,daemon OFF,Transport HC30/30/45/45/90 | source_labels_are_not_full_module_verification, CPU/memory benchmark 미실행을 명시 |
| `transport83-native-build-actual-root-r1-20261017.safe.json` | sourceac57/Commonc485, 기존 parent 기반 native image3a273 build exit0 | 현재 main 공식 Dockerfile의 clean build·provider Chromium 실제 수집과 다름 |
| `transport83-cpu-before-after-closure-root-r1-20261017.safe.json` | 10월16일19:01 UTC 마감,같은 Geo5+Transport5 idle90초×3: host19.472%→7.526%, post OOM/restart 증가0 | 수집 job0·Weather/global web/daemon/관측 stack OFF의 제한 창. 현재77/16 또는 수집 부하 전체 CPU 개선율로 확대하지 않음 |
| `transport84-local-docker-contract-d-r3-20261017.safe.json`(D 수행) | 현재 af8 archive95 PASS/0 SKIP,실제 rsync old/new env보존,read-only/netnone | 전체 backend suite·공식 제품 image·실제 운영 deploy가 아님. 초기 fixture 실패 결과 보존 |

PG/RustFS HC10→30의 공유-plane 적용 잔여는 root 공통 감사/Manager lane이며 Transport 신규 patch가 필요하다는 뜻이 아니다. 최신 root 조회에서 PG/Rust10·cAdvisor30이 관측됐으므로 cAdvisor HC를10초라고 잘못 잡아 다시 바꾸지 않는다. 이 감사는 공유 서비스 재시작을 수행하거나 권고 실행하지 않는다.

## 다음 순서

1. 이 문서와 백로그 최신 요약을 정산하고 독립2리뷰 후 문서 PR을 머지한다. 사용자 지시에 따라 docs-only commit에 [skip ci]를 쓰며 코드/config/tests/workflow·운영 변경은 없다.
2. source 완료/운영 미검증 경계를 바탕으로 metadata와 공식 ARM/browser·새 bundle·T05 수용 계획을 준비한다. legacy M·DB·이미지는 보존한다.
3. 사용자 수집 재개 승인 뒤에만 collector 성공/실패·CPU/RSS/보호 유예·Map export를 실제 동일 조건으로 수용한다. 그 전에 daemon을 자동 복구하지 않는다.
4. PR81 고유 분산·지역 영속 분산 수집·API 지연/데이터 품질을 각각 별도 작은 작업으로 처리한다. 옛 PR/체크박스 전체를 한 번에 머지/삭제하거나 기간/timeout 완화로 PASS를 만들지 않는다.
