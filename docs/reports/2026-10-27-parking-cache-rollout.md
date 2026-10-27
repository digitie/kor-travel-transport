# 주차 통계 중복 조회 개선과 운영 수용

이 문서는 PR144의 소스 검증과 이후 운영 수용을 분리한다. 소스 머지·운영 배포와
예약 수집에 따른 통계 갱신을 확인했다. 최초 모바일 조회 지연과 비행편 표시 결함은 남겼으며,
아래 각 결과를 전체 UI·성능 수용 완료로 확대하지 않는다.

## 문제와 변경

기존 운영본 `7f01b0133dad73843ce61444830b1020cfd32f0a`에서는 예약 수집의 새 관측과
분석 캐시 갱신을 확인했지만, 원본 저장 뒤 파생 계산에 395.594초가 더 걸렸다.
최초 Firefox375 분석 요청의504도 보존했다. 이후 성공 응답은 최초 실패를 소급해 없애지 않는다.
[기존 배포·자연 갱신·실제 화면 원장](2026-10-26-parking-production-rollout.md).

[PR144](https://github.com/digitie/kor-travel-transport/pull/144)는 공항별로 필요한 관측 필드만
한 번 읽어 전체 공항과 활성 주차장 범위에서 재사용한다. 원본 JSON·전체 ORM의 반복 전송을 없애며,
API 응답·시간 창·중복 선택·이벤트 이름/순서·비활성 주차장 이력·빈 활성 주차장 처리를 유지한다.
10분 TTL·첫 원본 조회 전의 생성 watermark·지연 적재 무효화·수집 lease·원본/파생 롤백 경계도 유지한다.
DB 스키마·SDK·의존성·Compose·프론트엔드 변경은 이 PR에 없다.

- 최종 검토 HEAD: `a316691cf294bc15e6bcdbbbee37d1ad40bbcfc4`.
- 머지된 후보: `3691a07ab5bca36060173294c7d02c7399b76e4c`.
- 선행 main: `d7c36c3c99dafdefe4bc0100fd797662a2b4afd3`. Manager 정본 instance 소비 PR139를 포함한다.
- 검토 HEAD와 머지의 전체 tree: `8ff4c4fa533a67a405954fc0b885abb05370c044`로 동일하다.
- 기존 불변 로컬 전체와 최종 후보의 app tree: `b7855ba365f4b251bad617eab76344e36bdea200`로 동일하다.

## 완료된 소스 검증

| 구분 | 정확한 대상과 결과 |
|---|---|
| 최종 HEAD 직접 CI | push1268·PR1269의 backend/frontend/admin 총6개 SUCCESS. 백엔드 각각1299통과/2건너뜀. workflow_dispatch 전용 live-e2e 건너뜀은 실제 UI 통과로 세지 않는다. |
| 불변 로컬 전체 | `af033ac794929807bfacb71a1eb1353a3f1a57ad`: WSL1222통과/23건너뜀/4312.31초, PostgreSQL Docker1239통과/6건너뜀/3895.15초. 두 exit0와 독립 docker wait0, 원본·독립 로그 해시 일치를 확인했다. |
| 최종 HEAD 집중 | WSL95+46=141통과. Docker140통과/1건너뜀. Docker의 rsync 부재 사례는 같은 WSL 사례가 통과했다. |
| 합성 해석 | 로컬 전체를 최종 HEAD에서 직접 재실행했다고 표현하지 않는다. 불변 소스·fixture의 mode/blob와 최종 집중 범위를 대조했으며, 최종1301개는 불변1160개와 집중141개로 구성된다. 최종 HEAD 직접 전체 결과는 위 CI다. |
| 독립 적대 리뷰 | James·Popper가 정확 최종 HEAD의 잔여 P0/P1/P2 없이 소스 PASS. Popper 독립 guard16통과. James의 새 pytest는 의존성 부재로 미실행이며 소스/저장 증거 검토와 구분한다. |
| 추가 경계 | 연결 query override와 import 시계 오염을 각각 무접속 실패→수정으로 확인했다. 한국 자정·7/14/21일 경계·소스/수집시각/ID 우선순위·빈 범위·watermark·롤백/경합을 검증했다. OpenAPI와 공백 검사 통과. |

정본은 로컬 소유 폴더 `C:/Users/digit/.codex/tmp/parking-cache-compact-acceptance-20261027/`의
`final-verification.json`과 `final-evidence-manifest.json`이다. 원장45개를 재해시해 불일치0을 확인했다.
원래 실패·건너뜀·취소 기록은 보존한다.

동일 합성35,696행·2공항·8범위·21일·5분 관측·행당4096자 JSON에서 전체32개 결과와
생성/원본 관측 시각이 네 번 일치했다. 기존6.212/5.216초에서 수정0.970/0.945초,
관측값 SELECT32→2·원본 JSON SELECT32→0이다. 해당 Python 프로세스 최대 RSS는
235196/235264KiB→88044/87740KiB였다. 이 합성 결과를 운영 지연·전체 CPU/RAM 개선으로 확대하지 않는다.

## 배포 입력과 기존 작업 보존

로컬에서 검증한 준비 압축파일은 소유 폴더 `parking-cache-release-3691a07a-20261027/lf-git-config/`의
`candidate-3691a07ab5bca36060173294c7d02c7399b76e4c.tgz`다.
SHA256은 `ab61b69f72c83fcad18ae3be40dbf05f1706a785077366d9566c4c35cc655ee8`,
2,964,878바이트·전체931개/일반파일788개/디렉터리143개다.
PAX의 full SHA와 일반파일788개의 Git blob·mode, 공식4파일과3 heredoc을 확인했다.
처음 Windows Git에서 생성한 CRLF 압축파일은 부적합 원본으로 보존했고 배포 입력으로 사용하지 않는다.
채택본 생성 명령에만 LF 설정을 적용했으며 영구 Git 설정은 바꾸지 않았다.
다른 배포 담당이 같은3691 후보로 시작한 실제 운영 입력은 그 실행의 source proof에서 별도로 확인한다.
로컬 준비 압축파일의 해시를 실제 사용 원장으로 자동 대입하지 않는다.

12:33:37 KST 읽기 전용 관측에서는 다른 승인 배포인
`kt-transport-final-d7c36c3c-20261027-retry1.service`가 G를 보유하고 백엔드를 사전 빌드 중이었다.
공식 staging의 `.release-sha=d7c36…`는 실제 이미지 교체 완료 증거가 아니다.
그 작업·자식·빌더를 중지하거나 새 빌드와 겹치지 않는다. 실제 OLD·다섯 이미지·schema·Manager4필드는
기존 배포와 선행 Weather 교체가 끝난 뒤 새로 고정하며 과거7f01 관측을 자동 재사용하지 않는다.

해당 선행 배포의 백엔드 사전 빌드는12:39:16 KST에4539.896초/exit0로 끝났으나,
다음 단계에서 `Cancelled`로 중단됐다. 빌드 실패로 기록하지 않는다.
12:39:51 KST unit 종료1/MainPID0, G 해제, `ABORTED_ORIGINAL_RUNTIME_VERIFIED`,
instigator pause 없음·자식 종료 확인·원래 빌더 STOPPED 복원을 확인했다.
12:44:13 KST의 별도 읽기 관측에서 두 receipt7f01·기존 다섯 이미지 healthy와 기존 단일
instance bind를 확인했다. 이 관측은 선행 Weather 교체 후의 최종 배포 baseline을 대신하지 않는다.

## 운영 수용과 남은 범위

13:00:18 KST에는 같은3691을 대상으로 한 별도 승인 실행
`kt-transport-final-3691a07a-20261027-main144.service`의 G 보유·수집 drain을 확인했다.
13:04:14 KST 관측에서는 상태 백업과 drain을 마친 뒤 공식 backend 전환이 실행 중이었다.
별도 일회용 준비본은 baseline 미고정 상태로 보존하며 중복 빌드·교체를 실행하지 않는다.
이 실행의 완료 원장·복원과 실제 화면/자연 수집 검증을 이어받는다.

13:13:11 KST 해당 실행의 `DEPLOYED_VERIFIED`와 원래 instigator 복원을 확인했다.
API·관리자 full SHA는3691이고 다섯 역할 healthy·schema0035·CS12306/location이 일치한다.
새 backend/CS 이미지는 `sha256:ecd76e54aa473aabf4d3c02cf2d548236070994260cdce3437f6ec8313c919d6`,
관리자는 `sha256:69b1813269b9112585821fe5c5cb258969f2b5b04519e3be6bbfc09af6199f20`다.
실제 source proof의 입력 압축파일도 위 로컬 준비본과 같은 `ab61b69f…55ee8`/931항목이었다.
새 상태11,462개를13:01:08 KST에 백업해13:10:07 KST의 새 CS에 uid/mode/내용까지 대조했다.
과거10,509개를 재사용하지 않았으며 그 이후 새 artifact도 보존했다.
Manager가 반환한 Odroid 상한5의 내용 주소 instance 파일과 실제 CS 단일 read-only bind를 확인했고,
컨테이너 내부 파일 SHA256도 `a7d907c4d54024e2868c1c9db0e6d775a351bfc1d0001de378983e8a2c7bc9db`로
일치했다. 다른 호스트 consumer의 실제 수용까지 완료했다고 해석하지 않는다.

이 unit은 종료 후 `--collect`로 수거됐으므로 `systemctl show` 기본 ExecMainStatus0을 종료 코드 증거로
사용하지 않는다. 정확 invocation `443022c2b036458bac3df58232f0e94d`의 PID1 성공 deactivation과
원래 controller PID1384093의 journal 연결, 부모·cgroup 소멸을 대조했다. 정본 `unit-completion.json`의
숫자 종료 코드는 미제공으로 남겼다. 이 판정의 무접속14개 경계를 확인한 뒤 성공 proof를 회수했다.
독립 회수 디렉터리는 `/var/tmp/codex-parking-deployed-proof-3691-20261027.qtbcpfez/`다.

새 운영본의 실제 화면·자연 수집에서 다음 항목을 각각 확인했다. 최초 실패와 남은 한계를 함께 보존한다.

1. Manager G→Transport R, NVMe, 실제 OLD와 다섯 이미지·schema35·정본 instance를 검증한다.
2. Transport 원래 instigator 상태를 새로 저장하고, 해당 실행·대기·실제 worker 자연 종료 뒤 상태를 보존한다.
3. 새 후보의 다섯 역할·API/관리자 full SHA·CS12306/location·원본 상태·환경/다른 서비스 보존과 원래 builder 복원을 확인한다.
4. 새 baseline 이후 시작한 실제 예약 공항 수집에서 원본 저장과 통계 캐시의 생성/원본 관측 watermark를 대조한다.
5. 원본 수집 소요와 원본 저장 뒤 Dagster 종료까지 지연, 실제 모바일 최초 응답 HTTP/시간을 각각 기록한다.

첫 배포 후 자연 run `2713b386-a4a4-44fc-b9dc-317cd1e1b93b`는13:15:59.279725→13:20:16.591654 KST
SUCCESS/257.312초였다. 원본3080의 저장 종료13:17:45.562549에서 job 종료까지151.029초다.
이 run은13:20:05.424153 KST의 새 읽기 baseline 이전에 시작했으므로 baseline 이후의 엄격한 새 run으로
대체하지 않는다. 정확 commit 시각은 별도 기록 필드가 없어 generated_at이나 관측 시각으로 꾸미지 않는다.
13:25:46 KST에는 활성 주차장을 동적으로 대조해14공항/58범위/232개 기본 캐시가 TTL 안임을 확인했다.

첫 실제 Native375 분석은13:19:19.585→13:19:32.556 KST HTTP200/12.971초였다.
headers까지12.191초·본문 JSON 완료까지 추가0.780초로 나눴다. Native1440은5.546초,
후속 Firefox375는13:24:47.283→13:24:48.159 KST HTTP200/0.876초였다.
첫 느린 표본을 후속 빠른 표본으로 덮지 않는다. 당시 우리 Weather r3는 수집 drain 단계였다.
이후 Weather schema0033에 새 migration과 일치하는4개 인덱스가 이미 있음을 확인했지만 생성 주체·시각은
미확인이다. 이를 우리 r3의 신규 DDL로 기록하거나, 초기 Transport 지연의 원인으로 귀인하지 않는다.
Native 원본의 flight DOM0·로그아웃 이벤트 미포착도 실패로 보존한다. 로그아웃은 auth cookie와 선호 cookie를
구분한 별도 좁은 확인에서303/auth1→0을 확인했다. 항공편은 실제14.767초의 성공365편을6초 client timeout이
버리는 제품 경계를 확인해 별도 작은 UI 후속으로 수정한다. 첫 원본의 종합 실패를 성공으로 바꾸지 않는다.

13:20:05 baseline→13:35:42 KST의 엄격한 대조에서는 이후 시작·성공한 예약run3082/f704와3084/009d,
김포 신규 관측10개·기본 캐시24/24행·활성6범위의4 metric과 원본 관측 watermark 일치를 확인했다.
13:38:42 KST 전국 관측은58범위/232행이 TTL 안이었지만 새 원본13:37:16~20이
직전 캐시 생성13:31:43.794076보다 나중에 저장된 계산 중 구간이었다.
TTL 안이라는 사실을 새 원본까지 반영한 사용 가능232행으로 바꾸지 않는다.
13:42:10 KST에는 전공항 generation이13:37:22.965956으로 바뀐 것을 확인했지만 다음 원본이 이미
저장돼 있어 그 계산 중 표본도 보존했다. 최종13:45:40.476067 KST에는14공항/활성58범위/동적 기대232행,
TTL 내232행과14/14공항의 generation이 최신 원본 collected_at 이상임을 함께 확인했다.
해당 자연 run `10d5c1c9-089f-4f3f-9f3a-2be1dbd6bfab`는13:40:51.010862→13:43:07.562879 KST SUCCESS,
원본3087 종료13:41:40.079322에서 job 종료까지87.484초였다. 직전 완료 run도95.672초였다.
서로 다른 운영 표본의 관측이며 부하를 통제한 CPU 계량이나 정확 cache commit 시각으로 해석하지 않는다.

새 baseline 이후 완료한 네 예약 run의 원본 저장 종료→Dagster 종료는 각각
105.370/86.421/95.672/87.484초로 모두5분 이내였다. 엄격한 두 run에서는 전국 신규 관측88개도 확인했다.
최종 원장은 `parking-runtime-acceptance-20261027-3691a07a-d26abe37636d/` 아래 후보3691 폴더의
`final-runtime-acceptance-7efbd3ea-9574-42fa-a45f-b3c85dfb1a31.json`이며,
`evidence-manifest-e90d88e278074e609a5a49ee0d9a94ac.json`의29개 원본은 WSL/Windows 해시가 일치했다.
판정은 `NATURAL_REFRESH_PROVED_WITH_FIRST_UI_LATENCY_MISS`로 첫 조회 지연을 남긴다.
자연 수집 관찰은 읽기 전용 DB6 transaction·metadata5회이고 수동 job·직접 provider GET·DB 쓰기는0이다.
정상 UI의 항공편 API GET은 기존 메모리 TTL 만료 때 원천 조회를 유발할 수 있어 이0회 주장에 포함하지 않는다.
늦은 응답을 무시하는 UI 후속은 [PR147](https://github.com/digitie/kor-travel-transport/pull/147)의
`95f86b2d6d93f3655dbd79af9001ac5869fb8536`으로 분리했다. 이 문서의3691 운영 수용에는
해당 수정의 머지·배포를 포함하지 않는다. 실제 콜드 조회 지연, 미분류 tilefailed2개·로그아웃 후401 표본도 보존한다.

수동 수집·job 실행이나 추가 provider 호출로 자연 갱신 수용을 대신하지 않는다.
T-PARK-01/02는 운영 성능 수용 전까지 열어 두며, 이전 약15시간 관측 공백·최초504는 보존한다.
철도·버스·유가·고속도로·전체 지도 작업도 이 성능 PR의 완료로 닫지 않는다.
