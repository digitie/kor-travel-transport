# 주차 원본48시간·통계영구 작업 재개 감사

## 현재 정책과 운영 경계

사용자 정책은 원본48시간·집계통계영구다. 운영 완료가 아니다. 이번 감사에서 운영DB/SSH/태그/컨테이너/스케줄·provider·prune 실행은0이며 원래3f516 배포 입력은 수정하지 않는다. 실제 운영 schema는 별도 Root 관측의 정본이며 이 보고서가 재조회한 값은 아니다. source main의0036 공항통계와 PR161의0037 전국/보류/최신 요약은 아직 운영 수용되지 않았다.

## 고정 PR·검증·의존관계

| PR | 정확 head/base | 현재 수용과 남은 gate |
| --- | --- | --- |
|161|c76361badd6c34ecf8f00463fa5ef1c329598261 / main, 최초기준8bc25638|Draft/open/mergeableFalse. exactc763 James·Popper SOURCE_PASS(잔여P0/P1/P2없음). CI40554550813 backend/frontend/admin SUCCESS·live SKIPPED. 최신 main3f516 통합 뒤의 증분 검증·새 head 두 리뷰가 필요하다.|
|162|f4ea9e096b421d626133f72835f02ce90f92024a / codex/parking-retention-stage2a(c763)|Draft/open. CI40555715377 세 job SUCCESS·live SKIPPED. pure pattern reader의 WSL/Docker 각11PASS/actual0·wait0. 독립 두 리뷰는 아직 미확인. 실제 API 호출0.|
|163|ec9a4866b08e264ce3a491287a7fe563a430e265 / codex/parking-retention-stage2b(f4)|Draft/open. CI40559457056 세 job SUCCESS·live SKIPPED. 단일snapshot DB adapter의 WSL/Docker 각20PASS+48subtests/actual0·wait0. 독립 두 리뷰 미확인, 실제 API/cache/bundle 호출0.|

GitHub read-only 조회로 current main3f5160a0d5e0c246fa744864998a3fc805542ce4를 확인했다. 세 소유 WT는 clean이다. 원 c763/350/d2 및 집중/whole/실패 원장은 보존한다. d2 whole은 WSL1466PASS+6subtests/2skip, Docker1462PASS+6subtests/6skip actual0·wait0의 수정 전 기준선이다. c763 정확 CI backend1476PASS+6subtests/2skip과 섞지 않는다. 현재 PR161 body의 “d2 Docker 회수중”·문서의 “c7리뷰중/2A구현중” 표현은 이번 통합 문서에서 작성시점 이력과 현재 상태로 정리해야 한다.

CI SUCCESS와 live SKIPPED를 실제 UI 수용으로 세지 않는다. 162/163의 기여는 내부 동등성/DB snapshot 경계이며 전체 보존 정책 구현이 아니다.

## 현행 누락과 차단 조건

1. **Backfill/coverage:** 공항·전국의 immutable sufficient stats와 count/hash 검산은 있으나 수동 job은 하루/버킷 제한의 partial 작업이다. no_new_rows=not_audited다. 운영 backfill0이며 누락·무관측을 구분하는 연속 범위 coverage 정본과 완료 수용이 없다. 지연 재수신 issue는 영구 통계를 덮지 않고 차단하며 자동해소/force를 추가하지 않는다. raw가48시간을 넘게 남으면 보류이지 정책 성공이 아니다.
2. **Reader 실제 전환:** main/API/cache/outlook는 새 load_pattern_statistics/read_pattern_statistics를 호출하지 않는다. 7/14/21/28/90일과 공휴일 최대224일, 동일시각 전국cohort, 원관측10/50event와 합산시계열insights, 날짜별동일가중 outlook를 별도 의미로 전환해야 한다. 현재48시간 raw만으로7일 그래프를 축소하면 안 된다.
3. **정확도·시간 경계:** 10분 sufficient stats만으로 임의 cutoff/15·17·29분 간격을 정확 복원할 수 없다. 162/163은 precision unavailable을 예외로 드러낸다. 실제 기본14일 rolling cutoff가 bucket 내부를 자르는 경우의 requested/effective 범위·해상도·coverage 계약을 API/header/DTO 및 proxy/cache/bundle에 동일하게 연결해야 한다. 기존 하한-only API가 허용한 미래 관측을 임의 end=now로 삭제하는 회귀도 금지한다.
4. **원본 history:** 현재 기본/최대days 및 메모리·압축캐시는30일 계약이다. 실제48h cutoff/default2/max2·cursor410·partial/expired 원장, prepared bytes invalidation, public/admin 실제 소비 기본값을 함께 전환해야 한다. 만료된 cursor를 빈200으로 바꾸지 않는다.
5. **현재/Map export:** compact latest는 원본 없이 마지막 관측을 유지할 저장 기반일 뿐 current API는 아직raw를 읽는다. stale·observed/id tie·수신watermark를 유지해야 한다. Map typed current membership과 immutable generation/15분TTL/cursor의 삭제 전후 독립 DB 회귀가 없다. 다른 도메인export/collectionmetadata 삭제로 우회하지 않는다.
6. **영구 복원 보호:** full pg_dump는 새 통계를 포함하지만 같은 schema의 오래된 dump는 통계를2→1로 줄이는 실제 반례가 있다. pre-restore backup만으로 영구보존이 아니다. restore 전 통계세대/내용 단조성 또는 격리 복원검산의 명시 gate가 필요하다. 이관은 기존 guard를 유지하고 lot/airport identity/FK 의미를 보호한다.
7. **원문/실제정리:** 원본범위는 parking_snapshots와 정확한 KAC/인천 주차 endpoint 원문이다. fee/rail/bus/fuel/weather·unknown오류·기준정보·run/Dagster metadata를 건드리지 않는다. 각 후보의 전체 raw count/hash/통계/threshold/전국 membership·late commit lease 검산이 끝나야 bounded prune를 연결할 수 있다. 현재 prune_parking_raw는 항상 예외이며 그대로 유지한다.

## 현실적인 다음 순서와 새 리뷰 범위

1. 원 c763 WT/ref/원장을 보존한 새 관리 WT·codex branch에서 exactmain3f516을 통합한다. 사전 merge-tree는 docs/journal.md·resume.md·tasks.md 세 충돌만 표시했고 collection.py/definitions.py는 자동병합했다. 자동병합을 의미 검증으로 간주하지 않고 수집 lease/최신상태갱신과 Dagster job metadata/commit/Failure의 결합 diff를 따로 검토한다. main의 운용/SDK/UI/수집 개선을 되돌리지 않는다.
2. 현행 stage 표·resume/journal/tasks·PR161 body에 실제 종료/CI/두리뷰와 미활성 경계를 반영한다. 변경한 exacthead 및 main→head 전체diff/c763→head 통합diff를 고정한다. PG18 집중의 필요 범위는 새 combined collection/definitions/0037/legacy/latest/global/state/API unchanged 회귀다. 새 whole은 새 실패/변경·검증 필요 근거가 있을 때만 별도 조건을 고정해 시행한다.
3. PR161 통합 후보는 두 독립 증분 리뷰를 받는다. 162/163은 원문을 먼저 독립 두 리뷰할 수 있으나 새161이 정해지면 순서대로 main 증분을 병합해 정확한 최종 source/CI를 다시 결박해야 한다. 무단 merge/main push는 없다.
4. 이후 첫 실제응답 단위는 세 pattern의 DB reader와 cold/cache/bundle 계약이다. requested/effective cutoff와 미래관측·coverage/precision의 반례를 먼저 고정한다. 시계열·calendar/outlook/event/history48h/current/export/restore 수용 없이 prune를 켜지 않는다. 기존UI구조를 유지하고 필요한 API 정보만 보완한다.

이 보고서는 새 운영 성공이나 보존 완료 영수증이 아니다. 이번 감사 시점에 제품 파일 수정·새 whole·운영 실행은0이다.
