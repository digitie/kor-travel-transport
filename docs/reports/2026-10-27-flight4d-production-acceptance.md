# 항공편 지연 성공 수정의 배포·실제 화면·자연 통계 갱신 수용

2026-10-27 10:14 UTC의 PR149 머지 인계를 포함한 증거를 기준으로 정리한다. 현재 운영은
`4d49610b2083fd0a30bc5e6afcca0036889044d4`다. 이후 main의 유가 UI 변경은 운영에 포함되지 않는다.
이 문서는 기존 원장을 읽어 정산하며 새 배포·수집·제공자 직접 조회·테스트를 실행하지 않았다.
이후 상태가 바뀌면 별도 시각과 증거를 추가한다.

## 소스·운영·후속 작업의 구분

| 구분 | 정확한 상태 |
| --- | --- |
| 항공편 수정 [PR147](https://github.com/digitie/kor-travel-transport/pull/147) | 검토 소스 `95f86b2d6d93f3655dbd79af9001ac5869fb8536`, 직접 CI 6개 SUCCESS·두 독립 최종 소스 PASS 후 merge `4d49610b2083fd0a30bc5e6afcca0036889044d4`. 이 merge를 실제 배포했다. |
| 이번 배포의 변경 | 기존 6초 뒤에도 같은 항공편 응답을 기다려 늦은 성공을 표시한다. 자동 재시도 GET 없이 30초 상한·선택/효과 폐기 경계를 지킨다. 분석 콜드 CPU·DB·수집 변경이 아니다. [원인·제품 검증](2026-10-27-flight-late-success.md). |
| 유가 UI [PR150](https://github.com/digitie/kor-travel-transport/pull/150) | 최종 소스 `19e35fd1e5f30c3ba69c2b82434b6c236748150b`, 10:02 UTC merge main `a15e08b3103c6e4afd7adf3c34b924c60b38a38b`. UI와 history 타입의 두 파일만 바뀌며 **운영 미포함**이다. |
| PR150 검증 범위 | WSL·Docker 관리자 291개/타입/린트/빌드, 375/1440 fixture, 두 독립 최종 SOURCE PASS와 PR workflow `40479092885` 전체 SUCCESS를 확인했다. 동일 HEAD의 별도 push workflow `40479086710`에는 마지막 backend 1개가 당시 pending이었다. 모든 workflow 6개가 성공했다고 합치지 않는다. [날짜·모집단·fixture 한계](2026-10-27-fuel-history-comparison.md). |
| 철도 별칭 [PR149](https://github.com/digitie/kor-travel-transport/pull/149) | exact `536a3288b13d83e03a2f9fc15086d32df8b74094`는 WSL1314통과/2건너뜀·Docker1310통과/6건너뜀 exit0, 794파일 불일치0, CI 두 run의6개 SUCCESS·두 독립 최종 SOURCE 재확인 뒤10:14 UTC merge `ca59458b3276a9f80284c3e086f902fa66e5e64f`를 완료했다. 이 main은 PR150/a15도 포함하지만 **149·150 모두 운영 미포함**이다. FK·저장 시간표 전체 수용과 구분한다. |
| 별도 자동 참조 갱신 | provider 없는 preview/apply는 별도 WT에서 설계·순수 core 개발 중이며 운영 실행0이다. PR149의 소스 머지나 이번 배포로 완료 처리하지 않는다. |

PR149의 추가 QA93%/실패0·머지 미완이라는 최초 인계는 위 최종 완료 전의 이력이다.
최종 CI 정본은 로컬 `C:/Users/digit/.codex/tmp/rail149-536-final-ci-20261027.json`이고,
추가 전체 검산의 `final-whole-manifest.json`과 두 SOURCE 확인을 함께 보존한다.
기존 [철도 별칭 원장](2026-10-27-rail-composite-alias.md)의 미완 게이트 문장은 작성 당시 범위이며
위 최종 소스 검증·머지 사실과 현재도 미완인 운영/FK/시간표 수용을 나눠 읽는다.

## 공식 전환과 복원

이전 운영 `3691a07ab5bca36060173294c7d02c7399b76e4c`를 실제 다섯 이미지·schema35·Manager
정본과 결박한 controller r6, launcher r2로 전환했다. G→Transport R, NVMe, 공식 배포 원문과
3개 heredoc, 교체 전 새 기준 대조·사전 빌드·자연 drain·복구 경계는 유지했다.

- 실제 unit: `kt-transport-flight-late-20261027-r1.service`, controller PID `1961462`,
  invocation `3621ecf9166241929eafd581b65b6c37`.
- 실제 archive SHA256: `409454daacd645c2b87fb94725916d3d77402b5e6f6efec0c6a03d653a891489`,
  2,988,801bytes·936항목/793일반파일/143디렉터리. full SHA/PAX·Git blob/mode·공식 본문을 확인했다.
- controller SHA256 `a29a03694784d5e2c7bea7e3d590fabe483abd7ac02ae99417fd2d5dac1e73e5`,
  helper `1f9cecc6135a9f58c3ff64d7c16348b3b8ad7f3cc50afdf582803f51f2282643`다.
- 초기 launcher r1은 정확 bytes를 전송했지만 수신 6개 파일이 uid/gid1001·regular·nlink1·mode0775여서
  group-write guard가 root installer 시작 전에 거절했다. 당시 UPLOAD만 생성됐고 INPUT/audit ROOT/unit은
  미생성이며 앱 변경·build/tag/pause/dispatch0이었다. 실패 업로드와 원문은 보존했다.
- r2는 **새** UPLOAD에서 stdin bytes를 검산하고 `O_EXCL|O_NOFOLLOW`로0600 파일을 생성했다.
  root INPUT0700/files0600·`python3 -I -B` 명시 helper와 runpy 연결을 사용했다. 두 독립 r2 리뷰 뒤
  명시 호출했으며 실패한 r1 업로드를 chmod하거나 재사용하지 않았다. 로컬 권한 fixture의 실패→수정과
  순수117개 통과는 실제 운영 수용과 별개 증거다.
- backend/frontend/admin 사전 빌드 3개가 모두 통과했다. admin prebuild는2373.489초였다.
  09:26:32.657900 UTC에 Transport18개만 일시 중지하고 해당 run/worker의 자연 종료 뒤 새 상태를 보존했다.
  09:42:04.796692 UTC에 원래18 RUNNING/0 STOPPED로 복원했고09:42:04.813969 UTC에
  `DEPLOYED_VERIFIED`를 기록했다.
- 전환 직전 원본 CS `1e2710508c9ad8f774726a6b84a7ed9a50fa564be089eb4efad2cea1611797d8`에서
  새로 확보한 상태는12,628개다. manifest SHA256은
  `0dcf1b54b4f442ec5aa2e63969616ffc029405fba8bb7ce4ac30948bfa7a53d8`이며 새 CS
  `faa0205a74cce17e93b99dd96e9762ebef1ecb3e7e1c192bfd1e9509d35c153b`의 내용·uid/mode와 대조했다.
  이전3691의11,462개 snapshot을 재사용하지 않았다.

API/admin full SHA는 모두4d49610b, 다섯 역할은 healthy/running/not-paused, schema는
`0035_ferry_reference`, CS는12306/location `kor-travel-transport`다. 보호 env/overlay와 모든 외부
컨테이너는 baseline과 같고 공용 daemon은 RUNNING이다. Manager 내용 주소 instance
`a7d907c4d54024e2868c1c9db0e6d775a351bfc1d0001de378983e8a2c7bc9db`의 파일 해시·단일 read-only
bind를 유지했으며 소유 builder는 원래 STOPPED로 복원했다. 09:46:20.963008 UTC 독립 읽기에서도 확인했다.

unit은 성공 종료 후 수거됐다. 정확 invocation의 저널 성공 deactivation과 controller `finished`,
부모·자식 cgroup 소멸·G 해제를 결합해 판정한다. 수거 뒤 `systemctl show`의 기본
`ExecMainStatus=0`을 실제 숫자 종료 코드로 기록하지 않는다. `unit-completion.json`의
`numeric_exit_status`는 null이며 `result.json`은 child_known_ended=true/instigators_paused=false다.

독립 회수 정본은 `/var/tmp/codex-flight-deployed-proof-4d49610b-20261027.tganrjgc/`의
`result.json`, `postflight.json`, `source-proof.json`, `unit-completion.json`, `qa-proof.json`이다.
별도 복원 원장은 로컬 `C:/Users/digit/.codex/tmp/flight-late-release-controller-20261027/`의
`restoration-ro-20261027T094623297Z.json`이다. 저널/환경/인증 원문은 문서에 복사하지 않는다.

## 항공편의 실제 성공과 분리된 8초 재생

GMP·2026-10-27 KST·lot1에서 실행 전 정확 운영 proof를 확인했다.

| 브라우저/폭 | 첫 실제 항공편 HTTP200 | 실제 API/DOM 그룹 마커 | 통제 pending 관측 | 통제 성공 반영 |
| --- | --- | --- | --- | --- |
| Native Chromium156/375 hasTouch | 7,986ms | 365/365 | 6,351ms | 8,157ms |
| WSL Firefox157/375 hasTouch | 485ms | 365/365 | 6,301ms | 8,106ms |
| Native Chromium156/1440 | 275ms | 365/365 | 6,444ms | 8,170ms |
| WSL Firefox157/1440 | 1,627ms | 365/365 | 7,095ms | 8,115ms |

첫 Native375는 실제6초를 넘은 성공 응답이 표시된 근거다. 다른3개는 TTL 캐시 가능성이 있으므로
제공자/콜드 성능으로 일반화하지 않는다. 365는 공동운항을 묶은 **그룹 마커**이며 실제 편명 수가 아니다.
각 실행에서 분석 ready·실제 마커 DOM·client error0을 확인했다.

통제 재생은 같은 context의 첫 실제 항공편/분석 응답을 메모리에서 재사용해8초 뒤 전달한 별도 검증이다.
추가 backend flight GET0·논리적 항공편 요청1이며6,200ms 이상/8,000ms 미만의 fulfill 전에는
분석 ready/pending1/marker0·동일 선택 범위를 확인했다. 이후365개가 반영되고 pending/error가 사라졌다.
이를 새 제공자 성공이나 운영 응답 시간으로 세지 않는다.

현황의 관측 시각·보이는 lot행·loading0을 확인했다. 초기 현황에는15분 이상 지난 관측 안내도 있어
loading 해제를 현황 전체의 신선도 통과로 확대하지 않는다. 뒤의 자연 수집/최종 캐시 검증은 별도 시점이다.
현재 `/parking`에는 outlook 패널이 없어
NOT_APPLICABLE/별도 요청0이며 outlook 구현·수용 완료를 뜻하지 않는다. 실제 장치가 아닌 브라우저/hasTouch 검증이다.
Native375의 첫 본문은 미보존이며 재조회로 대체하지 않았다. 다른3개 보존본은 민감키/URL query를 제거하고
재직렬화한 DTO라서 원문 bytes 동일성·raw bytes SHA는 미계측이다. 마커 수·pending 문구는 DOM 근거와
첫 viewport PNG를 구분한다.

## Firefox375 지도와 종료 검증

실제 Firefox157/WebGL2에서 map18/18·fuel38/38 타일 이미지 HTTP200/failed0을 확인했다.
두 stage는 y239/h565/bottom804, viewport812의69.6%이며 가로 넘침0, 줌/닫기는44×44다.
줌7→8·MapLibre 출처 hit-test, 유가 상세 Escape·보이는 초점 복원·목록300행·지도 왕복
stage565/카메라 유지·확장666px와 복귀를 확인했다.

유가 범위의 평균1,852.76/최저1,765·가격시각2026-10-27T08:39:29.357235Z가 API와 일치했다.
이는 명시 목록 선택 전 완료 범위의 DOM/API 근거이며 PR150 통계 페이지 수용이 아니다.
최종 fuel PNG는 명시 선택 뒤 `통계 조회 중…` 상태다. 선택 후 새 마커/통계 data-ready나 즉시
camera readout 완료의 증거로 세지 않는다. 원래 완료 범위와 선택 후 재조회 경계를 분리한 정정을 보존했다.

map은 최초 places200(total849/items0인 묶음 응답) 뒤401 한 건이 있다. 로그아웃 경계 시각을 계측하지 않아
원인은 미확정이다. 타일/조작기 성공을 HTTP 전체 성공으로 확대하지 않는다. map 상세 선택은 NOT_RUN이며
상세 조작 수용은 fuel에서 확인했다. 같은 요청을 반복해 원본을 대체하지 않았다.

6개 실행 모두 logout303·인증 cookie0·browser/context 닫기·소유 Native/WSL Node0·runner/child 소멸을
확인했다. 타인 프로세스 종료0, 직접 provider GET·추가 수집·제품/운영 변경·재시도/warming0이다.
정상 UI GET 내부 TTL miss에 따른 기존 provider 요청 가능성까지0이라고 주장하지 않는다.

실제 UI 원장은 `/var/tmp/codex-flight-late-live-20261027/final-4d-20261027/`의
`2026-10-27-4d-live-acceptance.md`, `summary.json`, `manifest.json`, `png-harness-erratum.md`,
`receipt-r2.json`이다. 최종 receipt SHA256은
`fef69ddf95fd6b0c9ba819a432a597f2c4f3b5caf68bb511eb7b34942e54586f`다.
최종 PNG 정정 이전 원 receipt와 과거3691의 flight365/DOM0·504·roads429·유가 초기30px·달력 UNKNOWN도 보존한다.

## 배포 뒤 자연 예약 수집과 최신 원본 반영

새 baseline 09:43:59 UTC 뒤 수동 job 없이 기존 `airport_collection_job_schedule`의 자연 실행3개가
SUCCESS였다. location·schedule metadata와 저장된 원본 run을 연결했다.

| 원본 run | 실제 Dagster run | 원본 finish UTC | Dagster job end UTC | 원본 finish→job end |
| --- | --- | --- | --- | --- |
| 3181 | [f77bfca3-c106-4396-871e-1dbe39bacec9](https://dagster.digitie.mywire.org/runs/f77bfca3-c106-4396-871e-1dbe39bacec9) | 09:47:27.531220 | 09:48:42.083259 | 74.552초 |
| 3182 | [3df7e195-dbb9-4587-9497-2b782d0353f0](https://dagster.digitie.mywire.org/runs/3df7e195-dbb9-4587-9497-2b782d0353f0) | 09:52:23.799394 | 09:53:39.735523 | 75.936초 |
| 3184 | [06880b53-d8e8-46ec-a07c-f7158958d7d7](https://dagster.digitie.mywire.org/runs/06880b53-d8e8-46ec-a07c-f7158958d7d7) | 09:56:55.530129 | 09:58:18.585363 | 83.055초 |

이 간격은 원본 수집 종료 뒤 job 종료까지이며 정확한 캐시 commit 시각·순수 계산 시간·CPU 사용량이 아니다.
김포 새 snapshot15행, 원본 watermark 전진, 기본4 metric×6범위의24개 cache 갱신을
`final-comparison`의 PROVED로 확인했다. 항공편은 이 DB 적재가 아니라 별도 메모리 API 캐시다.

09:53:12 UTC의 중간 `all-airport-summary`는 TTL600초 안인232행에3181세대(생성09:47:27.764826 UTC)는
반영된 상태였지만 최신3182세대를 반영한 공항은0/14였다. TTL 유효만으로 최신 원본 반영을 선언하지 않고 그 표본을 보존했다.
최종10:00:05.401532 UTC에는14공항·58범위·232행 모두 TTLfresh이며, 공항14개 각각
`generated_at_min >= latest_collected_at`도 만족했다. 모든 활성 범위의 최신 원본 반영을 함께 확인한 결과다.

DB 확인은 REPEATABLE READ/READ ONLY·statement_timeout3초·lock_timeout500ms로 한정했고
provider 요청0·수동 job0이다. 정상 예약 job 자체의 수집은 기존 운영 동작이며 검증자가 새로 실행한 것이 아니다.
원장은 로컬 `C:/Users/digit/.codex/tmp/parking-runtime-acceptance-flight4d49610b-20261027-r1/`
아래 `candidate-4d49610b2083fd0a30bc5e6afcca0036889044d4/`의 다음 파일이다.

- `baseline-1793094228838-641zwlg0.json`, `after-first-1793094663330.json`, `after-final-1793095150016.json`
- `natural-metadata-1793094486609.json`, `natural-metadata-1793095138790.json`
- `all-airport-summary-1793094786455.json` — 중간 TTL 유효/최신 세대 미반영 원본
- `all-airport-final-1793095200493.json`, `final-comparison-1793095259424.json` — 최종 최신 원본 반영

## 남은 범위와 다음 작업

운영4d의 늦은 항공편 성공 표시와 배포 후 자연 통계 갱신은 위 범위에서 수용했다. 이전3691 첫 분석의
12.971초 콜드 지연과 후속0.876초, 이전 네 자연 run의105.370/86.421/95.672/87.484초 및
전국 최신 원본 반영은 [이전 원장](2026-10-27-parking-cache-rollout.md)의 역사로 유지한다.
이번147을 analytics 콜드 CPU/RSS·최초504·저장 분석1초 목표 해결로 해석하지 않는다.

다음 한 작업은 T-PARK-02의 최초 분석 콜드 지연을 같은 조건의 원본/cache/API/화면 시각으로 분리하고,
정확 원인과 검증 가능한 최소 수정 범위를 정하는 것이다. PR150의 향후 운영 배포/실제 가격 수용,
T-FUEL-04의 브랜드·관심 후보 추이, 모든 지도 소비자/실기기, 철도/버스 실제 이용 흐름과 outlook은
별도 미완이다. T-PARK-02·T-FUEL-04·지도·철도 상위 task를 닫지 않는다.

Weather의 운영/후속 소스는 이 Transport 보고의 수용 대상이 아니다. 다른 저장소의 배포 상태를
이번4d 성공에 합치지 않으며 Weather 파일은 변경하지 않는다.
