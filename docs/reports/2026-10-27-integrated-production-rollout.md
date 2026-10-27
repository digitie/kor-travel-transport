# 2026-10-27 최종 통합 main 운영 전환

## 최신 상태 — 3691 운영·공개 UI와 자연 수집 갱신 수용

#144까지 포함한 최신 main 3691a07ab5bca36060173294c7d02c7399b76e4c를
10월27일04:13 UTC(13:13 KST)에 배포했다. 새 빌드 전 원격 main을 다시 확인했고,
그 사이 진전된 #144를 포함하기 위해 d7c 빌드는 검토된 정상 취소 경로로 끝냈다.
취소된 실행의 원 다섯 CID·source·Weather/plane·builder 복원과 G/R 해제를 검산했으며
이 이력을 성공한 새 3691 실행으로 덮지 않았다.

실제 수용 원장은 transport-main3691-operating-acceptance-t-r1.json
(17fe38b0b5f3e9dea4591794d3c6aea3eec0a37b6b9db577386d64a20222c683)이다.
Transport 일정18개만 일시 중지하고 기존 active/queued run·물리 worker의 자연 종료 뒤
fresh 상태를 보존했다. backend·code-server·frontend·gateway·admin 다섯 역할 healthy,
API/admin full SHA·schema0035·설치된 수집/analytics 원본 세 파일의 정확 해시를 확인했다.
일정18 RUNNING·전용9415 builder STOPPED와 기존 자원 한도·G/R 해제를 복원했다.
새 컨테이너의 CS12306은 Manager 정본 a7을 read-only로 읽고 실제 내부 SHA가 같다.
공용 daemon/webserver 내부는 기존 c444이며 전체 plane 수렴을 완료한 것으로 쓰지 않는다.
Weather 이미지·컨테이너·instigator와 공용 PG/plane은 변경하지 않았다.
Weather job 상태는 자연 진행의 관찰이며 이 작업이 실행·취소하지 않았다.

### 후속 자연 schedule의 엄격한 갱신 검산 완료

첫 baseline 뒤 시작한 자연 두 실행3082/f70491b4·3084/009d661e의 schedule 태그·UUID와
Dagster/원본 성공을 연결했다. 김포 새 관측10개·원본 watermark 진전·기본 네 metric의
24개 cache 갱신·공항 전체와 활성 다섯 주차장의6개 범위 모두 fresh/advanced를 검산했다.
원장은 own parking 관찰의 strict-compare-next-w-r2.json
(570c009fbf1fc901a30d0f96b031739eb5cfe2b5616ae88c1be6dd91ed7e2ee5)이다.
원 before deba7219와 after 91af91a2, 원격 원본 result cac0701a·postflight ba3948d5의
전체 SHA를 해당 원장에 결박했다. 첫 비교 incomplete는 이 성공으로 덮지 않았다.
강제 job·일정 변경·추가 provider 요청은0이다.

실제 Dagster schedule 정본은 cron */5 * * * *, Asia/Seoul, RUNNING이다.
과거 시작 간격900초를15분 cron으로 확정하지 않는다. 별도 CPU30초 시도는 자체 시작
확인 때009d661e가 이미 SUCCESS여서 표본을 만들지 않았다.
transport-main3691-natural-airport-cpu-memory30s-actual-t-r1.json
(1b4a77a96d47f604ff3b12c25df6977939ce7af97fa6e23885233f6a1bd3715e)에
메타데이터1회·실제 CPU30초 측정0회를 남겼다. CPU 사용률0%라는 뜻이 아니다.

### 별도 자연 수집 중 CPU·메모리 현재값 관측

후속 단발 관찰은 자연 airport 실행10d5c1c9-089f-4f3f-9f3a-2be1dbd6bfab가
04:42:04→04:42:46 UTC의 두 경계에서 모두 STARTED임을 확인했다.
sleep 설정은30초지만 실제 CPU counter 표본은 컨테이너별36.10~36.14초다.
고정 CID/PID·image·시작 시각·재시작 수·healthy를 대조한 현재 사용량은 다음과 같다.

| 대상 | CPU 한 코어 기준 | 4코어 전체 대비 | Docker 메모리 사용량(MiB) |
| --- | ---: | ---: | ---: |
| Transport API | 35.637% | 8.909% | 228.93→206.61 |
| Transport CS | 66.576% | 16.644% | 550.42→608.57 |
| 공용 daemon | 16.959% | 4.240% | 165.93→165.89 |

원본 transport-main3691-natural-airport-cpu-memory30s-actual-t-r2.json
(90eb5831ee786a034654101c451805d86f0d9f738b9c631868d4941f6f69437c),
요약 transport-main3691-natural-airport-cpu-memory30s-summary-t-r2.json
(590cbf94212325c2aac8d24fe13462bc1cf98bce85b02cf0a63dbfbde7f8440f)에 결박했다.
메모리는 cache 포함 Docker usage이며 anon/file은 원장에 따로 남겼다.
RSS 원자료는 없어 null이고 working set을 RSS로 바꾸지 않는다. peak도 측정하지 않았다.
CS의 동시 작업·공용 daemon의 다른 프로젝트 연산을 이 airport 하나에 귀속하지 않는다.
비교 baseline이 없어 개선 감소율·원인·전체 호스트 CPU를 증명한 결과가 아니다.
메타데이터 두 번 외 강제 job·provider·온도 확인·설정 변경은0이다.

### 실제 공개 HTTPS UI32

정확3691에 결박한 기존 공개 시나리오32개가90.054초에 모두 통과했다.
원장은 transport-3691a0-public-ui-w-actual-r1.json
(9e8733e7a44b81bdb58e03eae4d02005d1bd9f2d8b2e8743702419740c64448c)이다.

- 실제 초기 script8개를 보류한 SSR에서 두 입력·submit 비활성화, hydration 뒤 활성화,
  오프라인 설정 대조 뒤 로그인200·Secure/HttpOnly 세션·새로고침을 확인했다.
- 교통762행·유가300행 목록과 각20개 실제 타일, 읽기 API200 10개를 확인했다.
- 로그아웃303·cookie 제거·보호 화면 로그인 요구와 실제 보호 GET401을 확인했다.
- JS·console·HTTP·일반 네트워크 오류와 domain write는0이다. 화면 전환의
  ERR_ABORTED23개는 별도 집계했다. 자기 세션·브라우저·컨테이너 정리를 완료했다.
- SameSite=Lax 관찰은 기존 HAProxy 검토 제외 범위로 남긴다. 비밀은 TTY/RAM/stdin만
  사용했고 echo fallback을 거부했다. 파일·환경변수·argv·로그로 저장하지 않았다.

공개 TLS 완주90.054초와 과거 loopback 후보26초를 같은 성능 전후 표본으로 비교하지 않는다.
이32개는 주차 네 뷰·분석 네 탭의 실제 운영 성능을 모두 검증한 결과가 아니다.

### 첫 자연 수집 관측과 당시 비교 한계

새 소스의 자연 airport_collection_job 2713b386-a4a4-44fc-b9dc-317cd1e1b93b와
dagster_airport 원본 실행3080이 성공했다. 실제14공항44개 관측과 김포5개,
기본 네 metric의24개 cache 갱신을 읽기 전용으로 확인했다.
전체 job257.312초, step175.896초, 원본 수집23.143초,
원본 저장 완료부터 job 종료까지151.029초다. 전체 job 시간과 종전 분석395초를
직접 퍼센트 비교하거나 CPU/RSS 감소 효과로 확대하지 않는다.

transport-main3691-first-natural-run-observation-w-r1.json
(e25cfeee6cc41001b77ef6c0cd18a1b1500245f8f1c110e6d2a10425e6be5b33)에
원 관찰·step/원본/전체 시각과 한계를 남겼다. 첫 baseline은 이 job 시작 후여서 기존
엄격한 새 schedule 연결 비교는 당시 incomplete였다. 이후 baseline 뒤 시작한 두
자연 실행에서 위 조건을 충족했다. 당시 비교·원 실패는 보존했고 강제 job·수집·추가
provider 요청은0이다. 실제 cron5분 정본은 위 후속 메타데이터로 확인했다.

주차 분석 hook은 기본 탭에서도 analytics와 flight 조회를 Promise.all로 기다리며
기본 flight fallback6초가 표시를 지연시킬 수 있다. 이는 소스 기반 가능성이고 과거
Firefox 지연의 확정 원인이 아니다. 이번 게이트에 flight 차단·API fixture를 섞어
정상 전체 live UI PASS로 쓰지 않았다. 후속으로 analytics ready와 flight 대기를
분리하고 API 응답 시간·화면 준비 시간을 따로 검증한다.
전체 수집 CPU/RSS 효과, 첫 모바일 주차 응답, 전체 지도/철도/유가 backlog와
완전 흡수 검증 미완 Draft128·93·81·38·31은 완료 처리하지 않는다.

아래 빌드·CI·안전 중단 절은 당시 시점의 이력이다.


## 재시도 시작 당시 체크포인트 — 정본 경로 정합화와 새 배포 시도

다른 Weather 빌드의 G가 자연 해제된 뒤 검토된 도구로 운영·중앙 env의 해당 키 하나만
정합화했다. 원본은 root-private NVMe에 백업했고 uid/gid/0600과 다른 bytes는 보존했다.
두 파일의 SHA는 e2b1에서969dbda2로 바뀌었고 서비스 재시작은 없었다.
정본 경로 equality가 false에서true로 바뀐 것과 나머지13개 strict 플래그를 실제 재검산했다.
정합화 수용 `transport-final-env-canonical-preparation-actual-t-r2.json`
(`a2b6f813c3de814681ac008bd156cfcacd22b333e1ae7ca54386cc8ed19e9012`),
후속 RO `5ee283174fc21c77a496c829ab54828bca3efa3a8afe13b31e5b0392fe048fdd`다.

최신 remote main이 여전히 d7c36임을 확인하고 `retry1`의 새 INPUT/감사 ROOT/unit으로
02:21:10 UTC에 G를 취득했다. source/archive·builder 제한·제품 guard·복구 계약은 그대로다.
이전 실행·원본 백업·원 실패는 덮어쓰지 않았다. 현재 교체·공개 UI 수용 완료는 아니다.
보존 비교는 재시도 직전 fresh 원장
`transport-final-d7c36-retry1-before-readonly-t-r1.json`
(`5fd5790e1473ab2112793144fb58cfdcb288675e57e75878d77ce9792319bf4f`)에 결박한다.
이 새 기준이 아래 첫 시도의 안전 중단 및 외부 builder drift 이력을 지우지 않는다.

## 첫 공식 교체 시도 이력 — 안전 중단, 원래 런타임 복구

세 사전 빌드는 모두 exit0이다. backend4787.234초, core frontend55.936초,
admin2198.929초이며 전체 수집의 성능 개선 계량이 아니다.
10월27일01:29:58 UTC에 원래 RUNNING18개인 Transport instigator만 중지했고,
01:33:14 UTC에 active run0·물리 worker0을 확인해 새 state를 보존했다.
공식 backend 스크립트는01:35:04 UTC에51.43초/exit2로 끝났다. timeout이 아니며
컨테이너 교체 전에 중단됐다. 원 다섯 CID/image/healthy·API7f01·schema0035를 검산하고,
18개 instigator와 builder9415 STOPPED를 복원했다. 공개 UI32는 아직 실행하지 않았다.

읽기 전용 후속 검산에서 `.env.prod`를 source한 뒤
`KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG`가 Manager show 정본 경로와 달라지는 것을
확인했다. 운영 파일과 중앙 파일에 각각 해당 키가 한 번 있고, 나머지13개 strict 플래그는
맞았다. 제품139는 독립 override 불일치를 거부하므로 교정이 필요한 실제 선행조건이다.
원 stderr는 저장하지 않았으므로 이것을 exit2의 유일한 원인으로 확정하지 않는다.
제품 거부 규칙을 유지한 채 두 파일의 해당 키 하나만 G/R 안에서 정합화하는 절차와
새 감사 namespace의 재시도는 두 독립 검토를 통과했다. 첫 도구 초안의 다중 파일 복구
결함은 순수 fault 반례로 보존하고 수정했다. 검토된 교정 도구를 실행했으나
`ManagerMutationActiveError`로 G 취득 전에 끝나 env·서비스 변경은 없었다.
다른 소유자의 잠금을 우회하지 않으며, 현재 교정·재실행은 미완이다.

안전 중단 뒤 별도 RO로 원5역할 metadata/mount 전체와 Weather3·plane2 식별자·시작시각,
내부 c444,9415 STOPPED/자원한도를 직접 대조했다. shared9598는 같은 CID/PID로 살아 있지만
CPU quota가 최초-1에서100000으로 달라진 외부 drift가 관측됐다. 이 controller는 해당
builder를 바꾸지 않았고 원상 복원도 시도하지 않았다. shared 자원 전체 불변으로 주장하지 않는다.

안전 중단 원장은 `transport-final-d7c36-first-attempt-safe-abort-acceptance-t-r1.json`
(`d7a32a3a973a08771938bf868f4487f0d3a3eaf6fa6c9c56cdfd16d81b3d0e89`)이다.
`transport-final-d7c36-official-guard-env-source-readonly-t-r1.json`에 선택한 불일치 bool만
남겼고 env 원문·자격증명은 저장하지 않았다. 아래 초기 진행 기록은 당시 시점의 이력이다.

## 초기 체크포인트 이력 — 빌드 진행 중, 운영 수용 미완료

대상은 #141·#138·#143·#139를 합친 main
`d7c36c3c99dafdefe4bc0100fd797662a2b4afd3`다. 검토된 #139 최종 b619와 전체 tree가 같고,
Root의 최종 merge 수용 원장 `transport139-b619-final-merge-root-r1.json`
(`fc9293dae834498e685b1d462fc1fca1a7bebe658d4ade42d026eb9be117a57d`)을 이어받는다.
이 문서는 현재 운영 배포 성공을 선언하지 않는다.

현재 런타임은 `7f01b0133dad73843ce61444830b1020cfd32f0a`다. 별도 소유 unit
`kt-transport-final-d7c36c3c-20261027-final2`가 10월26일23:29:52 UTC에 정본 G를 취득하고,
원본 다섯 역할·이미지·설정·타 서비스 상태를 보존했다. 23:32:25 UTC부터 backend 사전 빌드를
한 번 실행 중이다. 이 체크포인트에는 Transport 일정 중지·서비스 교체·공개 UI 수용이 없다.
기존 [주차 배포·복구 기록](2026-10-26-parking-production-rollout.md)은 원문 그대로 유지한다.

## 소유 범위와 원본 보호

- 빌드·이미지·앱·cache·tmp는 기존 NVMe 경로를 사용한다. 원본 개발 checkout의 dirty와
  다른 작업자의 변경은 복사하거나 되돌리지 않는다.
- Manager G 다음 Transport R의 공식 순서를 유지한다. 사전 빌드 뒤 새 snapshot으로
  Transport instigator만 중지하고, queued/run과 물리 worker의 자연 종료를 확인한다.
- Weather 이미지·컨테이너·instigator·실행 중 job, 공용 PG·Dagster daemon·plane은 변경하지 않는다.
  `prepare-shared-dagster-cutover`와 공용 plane converge도 호출하지 않는다.
- 전용 builder9415의 원래 제한을 유지한다: CPU0.75코어, 메모리1.5GiB,
  memory와 swap 합계3GiB다. shared builder9598는 변경하지 않으며, 완료 뒤9415를 원래 STOPPED로 복원한다.
- 실제9415 부모 cgroup과 컨테이너 내부에서 `cpu.max=75000 100000`,
  `memory.max=1610612736`, `memory.swap.max=1610612736`을 확인했다.
  최초 `docker-init` 하위 `init`의 상속 값을 직접 한도로 오인한 검산 실패는 보존했다.
- 실제 현재 solve가9415 전용 builder에 속함을 확인했다. 선택한 프로세스 역할에서
  pip 하위 g++/cc1plus의 네이티브 컴파일을 확인했지만 구체 패키지와 전체 CPU 기여율은 수용하지 않았다.

## Manager 정본 소비와 복구 경계

정본 CLI show의 네 필드 `host/max_concurrent_runs/path/sha256`를 기존139 validator로 읽는다.
Odroid의 prepared a7은 기존 정책 max5·Geo1·Weather3·external2·slow1·WARNING을 보존한다.
살아 있는 공용 plane의 내부 파일은 여전히 c444이며 prepared a7과 별도로 검증한다.
호스트 alias가 현재 가리키는 파일과 기존 컨테이너의 bind inode를 같은 것으로 판정하지 않는다.

원 controller 초안은 이미지 rollback에서 Manager 경로를 전달하지 않는 P1 반례가 있었다.
실제 이미지 재생성 때는 후보 validator를 stdin으로 사용해 같은 네 필드를 다시 확인하고,
canonical path를 rollback 환경에도 전달하도록 정렬했다. CS는 같은 canonical Source의
read-only bind만 허용한다. 반대로 교체 전 중단은 원 CID·image·started_at·mount 전체가 같은
미교체 런타임을 검산하며, 새 경로에 맞추려고 컨테이너를 재생성하지 않는다.

재검증 parent 기한은 기존120초에 맞췄다. 제품 안쪽 hostname15초·registry60초·show30초는
변경하지 않았다. 원 P1과 원 실행 전 검산 실패는 지우지 않았다.

## 초기 검증 원장과 당시 남은 수용

- controller `f2c57159da8d03692efc9bda210aa64732c9aad4c50c194fc29db60fabb324ec`,
  helper `e4600b254981b3303d873139b5fc3fd34717851a0991a15335e746d93006b6e3`,
  archive `056b29e25e5a7f7d3cfd8d34e3a765311265366f33b6d1129b30064f8e37c226`으로 결박했다.
- 변경한 controller 경계는 Linux 순수26개0.133초와 Root/J의 독립 검토로 확인했다.
  Root `b4a2b08c9e1b98c8f9a76a8dc8bc405499169f27551974389f9671ca51f8c720`,
  J `3d7bf4558e76ed1fefaa8e4ce0cce2f5f236c86f2f9fea79e465b56878fce8a3`다.
  원 운영 controller의 역사적58개를 이번에 재실행한 것으로 세지 않는다.
- 사전 읽기 검산 `transport-final-d7c36-before-readonly-t-r1.json`
  (`17f1a796774c529f7761ebe58a4bac38d31bf830e33c6a159a3d2e605a4e8019`)에
  fixed Weather/plane container와 실제 plane 내부 c444·현재 active run을 남겼다.
- 실제 cgroup 수용은 `transport-final-d7c36-bounded-builder-actual-caps-t-r3.json`
  (`bf5aed904f11b919618bf810aca67d2ed32a9ef00027ac6e0a893c17a16a0aa8`)이다.
- 남은 수용은 세 사전 빌드 종료, fresh Transport-only pause/drain/state 보존, 공식 교체,
  API/admin fullSHA·다섯 역할 healthy·schema0035, 실제 CS canonical Source/RWfalse/insideSHA,
  Weather/공용 plane 보존, 원래 instigator 상태와 builder STOPPED 복원, 공개 TLS UI32다.

전체 수집의 CPU/RSS 감소, idle CPU·cadence·routine health 개선, 공용 plane 전체 a7 수렴은
이번 배포 완료와 같지 않다. 기존 [국소 scalar 계량](2026-10-26-plain-json-scalar-cpu.md),
[로그인 소비자](2026-10-26-login-hydration-common-adoption.md),
[Manager caller 범위](2026-10-26-manager-host-instance-caller.md)의 원 실패와 미검증 한계를 보존한다.
