# 자동 역 연결 미리보기·적용의 다음 작은 API 묶음

별도 `codex/rail-automatic-refresh` 작업트리에서 저장 입력만 쓰는 순수 계획·명시 DTO·DB 서비스와 관리자 API를 구현했다. PR149와 UI150을 포함한 main `ca59458`을 fast-forward로 통합했고 기존 작성 파일8개의 바이트와 UI150 파일을 보존했다. API·실제 전용 PostgreSQL을 포함한 WSL 집중56회귀가 통과했다. Next proxy/UI·전체 검증·CI·두 리뷰·운영 적용은 별도 미완이다. 운영 읽기/POST/수집/job·SDK·schema DDL 변경은0이다.

## 현재 확인한 경계

- registry는 외부 JSON 파일이 아니라 `kric_station_mapping_registry` id1의 JSONB 정본이다(`models.py:544–560`). FK는 `kric_station_codes.rail_station_id`이며 대상 단일 점유 unique 제약이 있다(:526–543). 따라서 이 묶음은 파일 교체가 아닌 같은 DB 트랜잭션의 registry/FK 변경으로 원자화할 수 있다.
- 기존 manual POST는 공통 reference advisory lock420054→registry FOR UPDATE→expected revision 비교→FK clear/flush/재배치→manual 전체교체→commit 순서다(`main.py:913–976`). 새 기능에서 이 POST를 자동 호출하거나 manual 배열을 client에 왕복시키지 않는다.
- 기준정보 수집은 provider 파일을 먼저 받은 뒤420054를 잡아 references를 반영한다(`rail_maritime_collection.py:129–169`). KRIC batch는 별도 session lease `hashtext('transport:kric_timetable')`를 사용하며, `_sync_codes`는 registry row를 잠그지만 reference 공통 lock을 직접 잡지 않는다(`kric_collection.py:44–55,173–220`). 단순 새 POST가 registry row만 잠그는 설계로는 기존 batch의 사전 references 읽기와 경쟁을 충분히 설명할 수 없다.
- UI는 이미 `/rail/mapping`의 목록/역별 편집/새로고침/JSON 내보내기 구조다. 서버 파일로 JSON을 저장하는 기능은 없다. 역별 note 초안은 `StationEditor` 로컬 상태이고 저장/서버값 갱신 때 effect가 초기화한다(`components/rail-station-mapping.tsx:40–50,160–184`).

## 고정한 관리자 API 계약

기존 manual endpoint를 유지한다. 새 backend resource는 **`/v1/transport/admin/rail-station-mappings/automatic`**의 GET/POST다. 기존 admin token 검증을 사용하며 인증 실패는404, 미준비 입력은503, 경합·이전 지문은409 문자열 `detail`이다. 성공과 알려진409/503에는 `Cache-Control: no-store, private`를 반환한다. 명시 DTO와 `docs/openapi.json`을 같은 변경에 반영한다. Next proxy는 기존 경로 아래 `automatic/route.ts`가 후속 후보이며 session·POST origin/JSON/본문 상한 검증은 그 계층에서 기존 패턴을 재사용해야 한다. 아직 proxy를 구현한 것은 아니다. provider/library wrapper는 없다.

| 호출 | 입력 | 주요 응답과 의미 |
|---|---|---|
| GET | 없음 | `expected_revision`, `candidate_revision`, before/after 자동·수동·미연결 수, 추가/해제/재지정/방법변경 목록, 수동 우선으로 제외된 후보/충돌, `can_apply`/차단 사유. 읽기 전용 preview다. |
| POST | `expected_revision`, `candidate_revision` 64자리 지문 두 개 | 서버가 같은 저장 입력으로 후보를 다시 계산하고 두 지문을 대조한 뒤 atomic 적용. 결과는 새 revision·요약·적용 건수다. manual/note 입력은 받지 않는다. |

GET은 새 READ ONLY/REPEATABLE READ snapshot으로 registry 원문·stored catalog·active code/FK·references를 읽고 기존 pure `automatic_station_mappings`/`effective_station_mappings`를 호출한다. 기본 load의 ‘automatic이 비었으면 임시 계산’ fallback을 실제 저장 baseline처럼 쓰지 않는다. 새 registry/캐시/CollectionRun/파일을 만들지 않고 `no-store, private`로 반환한다.

`expected_revision`은 기존 `mapping_revision(catalog_sha, old_automatic, raw_manual, reference_digest)`를 재사용한다. `candidate_revision`은 같은 함수에 **새 automatic과 동일 raw manual**을 넣어 만든다. 데이터 revision이 같아도 배포 사이 계산 결과가 달라지면 두 번째 지문이 달라져409로 막힌다. preview 서버 캐시·서명 토큰·새 테이블은 만들지 않는다.

stored catalog SHA/내용과 active code catalog가 다르거나 원문 입력이 누락/중복/불완전하면 GET/POST는 기준정보 미준비 오류로 거절한다. 후보가 계산되지만 실제 FK와 registry가 다른 무결성 상태는 preview의 `can_apply=false`와 blocker로 드러내고 무조건 고치지 않는다. provider 조회로 채우지 않는다. 숨은 raw manual/note도 서버 원문을 보존하며 visible14개만으로 덮어쓰지 않는다.

before/after의 `station_count`는 public_file 장소 수가 아니라 active 공식 catalog 코드 수다.
`mapped_count`는 해당 code의 effective 연결 수이고 `manual_mapped_count`도 유효한 수동 연결 수다.
코드2개/기준 장소3개 사례에서도 station_count는2다. 공개 후보에는 raw manual/note를 넣지 않는다.

## 동시성과 DB 원자성

**기존 batch를 수정하지 않는 가장 작은 보호 후보:** 새 적용 transaction이 먼저 같은 KRIC 식별자의 `pg_try_advisory_xact_lock(hashtext('transport:kric_timetable'))`를 취득한다. 배치가 session lease를 보유 중이면409 busy로 즉시 종료한다. 이 잠금은 수집 실행·48시간 보호 해제가 아니며 트랜잭션 끝에 자동 해제된다.

PostgreSQL16 공식 문서는 같은 식별자의 session/transaction advisory lock이 서로 충돌하며 transaction 잠금은 종료 때 해제된다고 설명한다. 따라서 이 후보는 API가 긴 session 잠금을 pool에 남기지 않으면서 기존 KRIC batch와 직렬화할 수 있다. [공식 잠금 계약](https://www.postgresql.org/docs/16/explicit-locking.html#ADVISORY-LOCKS). 실제 별도 PG의 양방향 경쟁·rollback 해제 회귀를 통과해야 구현 안전성을 수용한다.

적용 순서 후보:

1. request schema/auth 검증 뒤 새 transaction에서 짧은 lock/statement timeout을 설정한다. 기존 export의2초/10초 패턴을 출발점으로 실제 workload에서 검증한다. timeout/경합은 안정된409 busy 사유로 바꾸며 자동 재시도하지 않는다.
2. KRIC try-xact lease→공통 reference lock420054→registry FOR UPDATE 순서로 취득한다. 공통 key와 KRIC 이름을 재사용해 drift를 막는다. KRIC 이름 상수를 기존 domain 파일에 두고 수집기가 같은 값을 가져가는 작은 추출은 가능하되 수집 의미/주기는 바꾸지 않는다.
3. POST는 **READ COMMITTED**로 잠금을 취득한다. RR은 첫 잠금 SELECT가 오래된 snapshot을 먼저 고정할 수 있으므로 사용하지 않는다. **모든 잠금 뒤** 현재 catalog/active codes/references/raw automatic/manual을 읽고 existing revision을 계산한다. stale expected revision이면409, 후보를 다시 계산해 candidate 지문이 다르면409다. GET만 RR READ ONLY다. [공식 격리 수준 계약](https://www.postgresql.org/docs/16/transaction-iso.html).
4. 원문 manual 배열/note는 ORM 객체에서 전혀 재할당하지 않는다. manual 우선·단일 target 점유를 유지한다. 제거/재지정/다른 노선 영향은 preview에서 명시하되 API에 KR/K4 밖 영구 차단 규칙을 넣지 않는다. 적용 계약은 무결성·수동 불변·정확 후보 지문이며 실제 운영 적용은 구체 diff의 별도 검토 후 수용한다.
5. **실제 FK가 달라질 code 쌍만** old FK를 비워 flush한 뒤 새 effective를 할당한다. 변경 없는 수백 행은 건드리지 않는다. A↔B 교환 시 필요한 두 행은 함께 clear해 unique 제약을 지킨다. automatic 배열·mapping 갱신시각만 같은 transaction으로 저장하고 catalog/SHA·active·last_seen_at·수집 run/달력/시간표·원본파일·provider 상태/48시간 due는 바꾸지 않는다.
6. 한 번 commit하고 반환한다. flush/unique 실패·취소·예외는 전부 rollback해 manual/automatic/FK가 이전 상태로 남아야 한다. 동일 후보 no-op은 불필요한 쓰기/시각 갱신을 하지 않는다.

known writer의 순서는 manual/reference가 공통 lock 이후 registry, KRIC batch가 KRIC lease 이후 registry다. API는 KRIC lease를 try 방식으로 먼저 취득하므로 실행 중 batch를 기다리며 공통 lock을 쥐지 않는다. 외부 provider나 calendar 요청을 잠금 안에서 새로 수행하지 않는다. preview는 잠금/쓰기 없이 RR snapshot만 사용한다.

## 변경점만 보여주는 작은 UI

기존 toolbar에 ‘자동 연결 미리보기’ 한 버튼을 추가하고 현재 UI 구조/톤은 유지한다. 얕은 dialog/drawer에서 before→after 건수와 실제 변경 행만 보인다. 기존 미연결 목록·수동 편집을 전체 JSON diff/요청응답 화면으로 대체하지 않는다. 긴 설명은 제목 옆 정보 버튼으로 접는다.

수동 target/note 초안이 dirty이거나 저장 중이면 자동 적용을 막는다. 초기값과 비교한 dirty 상태를 부모에 전달하는 최소 변경이 필요하다. 기존 requestSequence/AbortController 패턴을 재사용해 늦은 preview/GET이 적용 성공의 새 revision을 덮지 않게 한다. 409는 자동 재시도/자동 적용 없이 현재 preview를 stale로 표시하고 새 미리보기를 요청하게 한다.

‘돌아가기’는 preview를 닫는 **쓰기0 UI 복귀**다. 적용 후에는 새 응답/GET으로 요약과 선택 행을 유지하며 기존 편집 화면으로 돌아간다. ‘시간표 복구 완료’라고 표시하지 않는다. 적용 후 DB 원복은 자동으로 제공하지 않는다. 이 요구가 필요하면 old automatic baseline 보존+새 revision 보호를 갖춘 별도 복구 계약이 먼저 필요하며, manual POST/빈 배열/코드 rollback으로 대체하지 않는다.

## 최소 수용 테스트

현재 집중 검증은 WSL에서 pure11·기존 매핑25·실제 PG11·새 API8·기존 수동 API1, 총56개가 통과했다. RC 잠금 대기 뒤 manual/reference writer의 새 revision 거절, session lease와 xact lease의 양방향 배제 및 취소 후 해제, FK 교환, commit 전 flush 후 예외·취소·unique 실패 rollback, 변경쌍만 UPDATE, method-only FK 쓰기0와 no-op 전체 쓰기0를 확인했다. GET 쓰기0와 실제 FK/registry·관련 원본/달력/시간표 테이블 불변도 비교했다. 아래 전체 수용 조건을 모두 완료했다는 뜻은 아니다.

| 층 | 반드시 확인할 결과 |
|---|---|
| Pure | 동일 입력의 preview/digest 순서 독립성, KR/K4 unique와 alias 중복 거절, global number fallback 영향, added/removed/retargeted/method-only 분류, manual 충돌을 숨기지 않고 manual/note 불변 |
| 읽기 API | auth/미설정 거절, GET0쓰기·0provider/calendar/job, source/active/catalog 불일치 차단, 실제FK와 effective 차이 구분, baseline14를 raw 길이14로 가정하지 않음 |
| 쓰기 API | stale expected/candidate 각각409, 적용 성공 시FK+automatic만 변화, manual/note 원문 지문 불변, no-op쓰기0, FK clear 뒤 강제실패도 전체rollback, 기존 manual POST 의미/응답 보존 |
| 실제 전용 PG | KRIC session lease↔API xact lease 양방향 경쟁·busy·release, manual POST/reference writer가420054로 변경 중일 때 API가 기다렸다 commit 뒤새 revision을 읽어409, UI preview 뒤다른 manual변경409, 적용 중취소/unique오류 후락·부분FK·pool잠금누수0, FK 변경 행만 UPDATE |
| UI/proxy | session/origin/JSON/본문상한, dirty초안·pending중적용차단, 돌아가기0POST, stale409재미리보기, 늦은GET역전보호, 선택/검색유지, 모바일dialog폭·키보드focus복원 |
| 범위 방어 | SDK/provider/calendar factory를 호출하면실패하도록고정, collection_runs/raw responses/calendar/snapshot/48h 상태 변화0, export RR reader와FK/registry 일치 |

## 아직 필요한 입력과 결정

전체 영향 수는 r2의 필터된 서울5개/823자료만으로 계산하지 못한다. 같은 snapshot의 전체 active code·전체 KRIC references·raw registry 또는 노트를 숨긴 동일 snapshot 투영+원문 지문·최신 expected revision이 필요하다. 현재923자동/14수동/171미연결 baseline부터 재현한 뒤 후보를 비교해야 한다. 기존 raw manual의길이/유효성/숨은 항목, registry와actualFK 일치도도 아직 미확인이다.

제거·재지정/범위 밖 영향에 API 영구 차단 규칙을 두지 않는다. 구체 diff를 preview로 보여주고 동일 후보 지문·수동 불변·데이터 무결성으로 적용을 보호한다. 실제 운영 적용은 영향 수를 읽고 별도로 수용해야 한다. 운영 DB 원복까지 ‘복귀’에 포함할지는 별도 계약 문제이며 이 설계에는 UI 복귀만 포함했다. PR149 이후 새 묶음의 구현·검증·리뷰가 필요하고, 그 뒤에도 FK/요일별snapshot/신선도/실제UI 시간표 수용은 별도다.

