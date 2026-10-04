# James — transport 공용 Dagster/UI 적용 전 원본 적대 감사

- 실행 ID: `J-BASELINE-20261004-e00e634b`
- 관찰 시각: `2026-10-04 04:57:52~05:00:35 UTC`
- transport immutable base: `e00e634b8502cdd1060d735b250ece96fd9fc945`
- 비교 common: `090f98429453d8882150eb9e56ccae98e0e353a2`
- 비교 weather: `8ed94e744b89b0b3ffbc088441d7089068f5ae40`
- 격리: Windows Git show/rev-parse로 위 commit 객체만 읽었다. 원 작업자의 이동 branch/worktree source는 읽거나 수정하지 않았다. 이 보고서 파일만 소유한다. 상대 reviewer 결과를 받거나 참조하지 않았다.
- 진입 문서: transport CLAUDE.md, AGENTS.md, SKILL.md, hostile-review.md, agent-failure-patterns.md, resume.md 및 shared-db-dagster architecture의 UI/scoping 계약을 읽었다. 심각도는 hostile-review 정본의 P0/P1/P2를 따른다.
- 판정: **구현 전 baseline 감사 완료. 아래 P1 두 건과 적용 시 보존 계약을 후보 구현에서 처리해야 한다. 아직 후보 코드·CI·live UI의 승인 보고서는 아니다.**

## 기존 결함

### J-BASE-P1-01 — 요청 body의 상한을 전체 메모리 적재 후 검사한다

위치: `packages/kor-travel-transport-admin/frontend/lib/upstream.ts:22–26`, Dagster proxy `app/api/dagster/graphql/route.ts`의 boundedText 호출.

Content-Length가 없거나 실제 body보다 작으면 request.text()가 전체 입력을 읽은 후 TextEncoder로 같은 내용을 다시 복사한다. 인증된 요청이 chunked 대용량 body를 보내면 1MiB 정책이 읽기 메모리를 제한하지 못한다. OOM/GC pressure가 다른 admin 요청으로 전파될 수 있다. 이 판단은 코드 경로의 정적 재현이며 실제 대용량 공격을 실행하지 않았다.

최소 수정: weather의 bounded streaming reader 계약처럼 chunk byte 수를 누적하고 초과 즉시 reader.cancel() 후 413을 반환한다. Content-Length는 조기 거절의 보조 수단으로만 유지한다. Dagster proxy의 인증·Origin 검사를 앞에 유지한다. body가 상한을 넘어도 upstream fetch를 시작하지 않는 시험이 필요하다.

### J-BASE-P1-02 — upstream timeout이 header 수신에서 해제되어 body 정지를 제한하지 못한다

위치: `lib/upstream.ts:15–19`, Dagster proxy의 response.body 전달.

fetchNoStore는 fetch가 Response를 반환하는 즉시 finally에서 30초 timer를 지운다. upstream이 header만 보낸 뒤 body를 영구 중단하면 proxy의 upstream body는 이 deadline으로 취소되지 않는다. init.signal도 새 controller.signal로 덮어쓰므로 호출자가 제공한 취소를 보존하지 않는다. 기존 브라우저의 25초 signal은 UI를 보호하지만 서버 upstream의 완전한 body 수명 상한이라는 보증은 아니다.

최소 수정: Dagster 경로에는 body 소비 완료까지 살아 있는 AbortSignal.timeout과 caller signal의 결합을 적용한다. 범용 transport API의 정상 30초 집계 계약을 이번 변경으로 일괄 10초로 축소하지 않는다. 빠른 header/느린 body 시험과 caller abort 시험을 포함한다. 실패 시 기존 snapshot을 보존한다.

### J-BASE-P2-01 — 실패 로그인 후 비밀번호를 유지하고 submit 중복을 동기적으로 차단하지 않는다

위치: `components/auth/LoginForm.tsx:11–22`.

비밀번호는 controlled React state에 남으며 finally에서 지우지 않는다. submit 초입에 busy/inFlight 검사도 없어 React disabled 상태가 반영되기 전 연속 submit이 두 POST를 만들 수 있다. 서버 rate limit이 있으나 UI의 중복 요청과 불필요한 비밀번호 보존을 막지 않는다.

최소 수정: common LoginForm의 inFlight guard/password finally clear를 사용하고 transport가 HTTP/auth 오류 문구를 소유한다. 성공 redirect에도 transport sanitizeLocalPath를 유지한다. 현재 서버가 next를 sanitize하므로 baseline을 이미 악용 가능한 open redirect로 분류하지는 않는다. 실패 비밀번호 clear·동시 submit·403/429/503·네트워크 실패를 확인한다.

### J-BASE-P2-02 — active run 조회가 무제한이며 오래된 STARTING/CANCELING은 빠진다

위치: `lib/dagster-scope.ts:51–54`, `lib/dagster.ts:29–31`.

activeRuns에는 limit/cursor가 없고 STARTED만 조회한다. 쌓인 고아 run 전체를 한 번에 받아 json()와 화면 목록에 유지할 수 있다. 최근 30건 밖의 오래된 STARTING/CANCELING/QUEUED는 모니터에서 보이지 않는다. 공용 coalescing은 이 상태들도 예약 억제 대상으로 보므로 적용 후 운영자는 왜 job이 막혔는지 UI에서 놓칠 수 있다.

최소 수정: scoped active query는 유지하면서 bounded page와 cursor를 사용한다. pending/active 상태 범위를 정책과 일치시키고 별도 상태 표시를 제공한다. pagination을 임의 1page로 잘라 오래된 run을 다시 숨기지 않는다. 모든 page는 같은 transport location scope를 유지한다.

## 공용화 시 반드시 보존할 계약

1. **최근 이력과 전체 active를 분리한다.** 현재 DagsterTables는 activeRuns 중 runs에 없는 항목을 앞에 넣어 dedupe한다. 오래된 ferry run이 최근 30건에 없어도 표시하는 lib/dagster.test.ts 회귀가 있다. weather처럼 최근 목록만 common snapshot.runs에 넘기면 영구 정지 run을 숨기는 P1 회귀다. adapter에서 scoped active와 recent를 union/dedupe하거나 공용 DTO에 별도 active 계약을 추가한다. 최근 성공/실패 집계의 의미도 명시한다.
2. **metadata 실패를 정상 빈 목록으로 바꾸지 않는다.** repositoryOrError/runsOrError/activeRuns union 검사를 유지한다. 조회 실패의 alert와 마지막 checkedAt/snapshot 보존, abort/unmount cleanup, 중복 refresh 방지가 필요하다.
3. **실제 max-runtime과 운영 확인 기준을 혼동하지 않는다.** transport jobBudgetSeconds는 600/3600/7800/14400초의 조기 확인 기준이고 architecture의 기존 native 실행 상한은 14400초다. common은 maxRuntimeSeconds를 넘으면 “실행 상한 초과”라고 말한다. tags를 읽어 실제 상한을 전달하거나 정책 변경과 함께 기준을 갱신한다. 단순 jobBudgetSeconds 대입으로 native 상한을 넘었다고 거짓 표시하지 않는다. 완료 run의 기존 duration도 조사에 유용하므로 의도 없이 제거하지 않는다.
4. **GraphQL은 server 소유 named operation과 scope다.** `kor-travel-transport`, `__repository__`, `dagster/code_location` tag, public `https://dagster.digitie.mywire.org`를 보존한다. weather의 location 이름 또는 .dagster/repository 값을 복사하지 않는다. failure-log operation은 runId/cursor 검증과 같은 tag scope로 조회하며 1000 event/page·page/time budget을 가져온다. arbitrary query/mutation·scope override는 계속 거절한다.
5. **transport auth를 공용 UI로 옮기지 않는다.** Dagster proxy의 hasAdminSession→Origin→body 검증 순서, HTTPOnly/SameSite strict/session max-age/Secure 정책, 실패 로그인 rate limit, logout POST의 상대 303을 유지한다. 기존 logout form을 단순 GET link로 바꾸지 않는다.
6. **로그아웃 캐시 fence와 모바일 로그아웃을 유지한다.** AdminShell은 제출 시 dashboard-v1/v2 sessionStorage를 지우고 로그인 문서에서도 다시 정리한다. 이전 비동기 응답의 캐시 재작성 경합을 방어한다. transport는 모바일에서도 로그아웃을 유지하며 weather의 footer 숨김을 복사하면 회귀다.
7. **메뉴는 pathname boundary와 Next Link를 주입한다.** 기존 nested path·유사 prefix·단일 aria-current 시험을 보존한다. class active 자체는 공용 내부 클래스 계약이 아니므로 semantic selector로 시험을 갱신한다. common lg=64rem과 transport shell=62rem의 경계가 달라 993~1023px에서 좁은 세로 rail에 가로 menu가 들어갈 수 있으므로 둘을 정렬해 확인한다.
8. **키보드 scroll region을 잃지 않는다.** transport 실행/스케줄 표 wrapper에는 role=region, 한국어 aria-label, tabIndex=0이 있고 테스트가 이를 확인한다. common의 현재 table-wrap에는 이 속성이 없다. 두 표의 모바일 키보드 진입/가로 스크롤 접근성을 공용 component나 명시적인 소비자 계약으로 보존한다.
9. **한국어 cron·수집 보호 설명을 보존한다.** transport는 */5 및 45 */4를 각각 5분마다/4시간마다 45분으로 안내한다. common describeCron은 이를 원문 cron으로 fallback한다. generic formatter 또는 주입 계약으로 유지한다. KRIC48시간/버스72시간 보호·배편 누락 보충·성공이 전국 적재 완료를 뜻하지 않는다는 domain 설명은 transport adapter에 남긴다. 다른 화면도 쓰는 statusLabel의 throttled/shared_job/partial 의미를 Dagster enum으로 일괄 대체하지 않는다.
10. **tokens와 CSS 책임을 명시한다.** transport는 이미 Tailwind4 theme/base/legacy/components/utilities layer와 page-body gutter를 사용한다. common theme/tokens 및 @source를 추가하고 transport semantic 값으로 --kt-*를 매핑해 라이트/다크에서 위계·오류/포커스 대비를 확인한다. CSS import만 추가하여 common 기본 green과 transport blue가 충돌하지 않게 한다. 기존 page-body가 바깥 여백을 소유하므로 weather의 direct-child gutter를 중복 복사하지 않는다. UI archive/license/provenance/digest와 Docker vendor 복사를 고정한다.

## 후보 검증 범위

본 baseline 감사에서 runtime/build/CI/브라우저/공격 테스트는 수행하지 않았다. 실제 backend recovery/native retry/SQL/memory는 Popper 영역이며 이 보고서가 승인하지 않는다. 최종 후보에는 위 실패 시나리오의 시험, 두 독립 적대 리뷰, CI, n150의 live production UI/320·375·414·768px 및 rail breakpoint 관찰이 필요하다. 배포·Docker는 192.168.1.13에서 조작하지 않는다. 실행하지 않은 항목은 NOT_RUN으로 남긴다.
