# resume.md — 현재 인수인계

## 현재 상태

- **2026-09-29 PR #51 배포 완료·머지 보류.** API/code-server `840f585`, UI `55148d2`로
  n150 healthy·재시작 0. VWorld 로컬 키 반영, 탭·겹침 목록·타일 실패·최초 마커 문제를
  수정했고 두 독립 리뷰 완료. 운영 관리자 UI 421개 통과(4.1분). 항구 공식 좌표는
  749개 중 10개이며 한도 오류 5개는 24시간 신규 호출 유예로 보호한다. 추가 실수집 없음.
  기존 parking-radar 추가 검사에서 15개 통과·오피넷 약 48시간 노후로 1개 실패했다.
  최신성 기준을 낮추거나 제외하지 않았으며 유가 복구 범위 확대 여부를 사용자에게 물었다.
  [상세 검증·운영 지문·되돌림 자료](runbooks/pr51-validation.md). 아래는 이전 진행 기록이다.

- 2026-09-29 PR #51 재검증: WSL/Docker 전체 백엔드는 각각 340개 통과·4개 제외,
  후속 좌표 재검증 수정 범위는 각각 44개 통과·2개 PostgreSQL 전용 제외다. 전용
  PostgreSQL 28개는 모두 통과했다. Popper의 정상 무결과 좌표 잔존 문제를 `dc6ba5f`로
  수정했다. UI 전체 HTTPS E2E는 418개 통과·묶음 마커 1개 간헐 실패로 조사 중이며,
  배포 이미지의 탭/상세 32개는 통과했다. 운영 교체·live·머지는 아직 남았다.

- 2026-09-28 VWorld 키: 로컬 `kor-travel-map/.env`의 키를 transport 관리자 UI의
  Git 제외 `.env.local`과 WSL 검증 환경에 반영했다. 실제 키로 Next.js 빌드 성공,
  VWorld 타일 12개 `200 image/png`와 배경 지도 렌더링을 확인했다. 탭/상세 E2E는
  최초 31개 통과·1개 실패였다. 재조회가 열린 겹친 장소 목록을 닫는 원인을 수정한 뒤
  32개 모두 통과했다. 키 값은 출력하거나 커밋하지 않았다. 운영 재배포는 아직 미완료다.

- **2026-09-28 12:24~12:33Z ADR-010 운영 식별자 개명 cutover 완료.** R=`b75fca1c`(#49).
  - 운영은 이제 project `kor-travel-transport`, 디렉터리 `/home/digitie/apps/kor-travel-transport`, 컨테이너
    `kor-travel-transport-<service>-1`이다. 여섯 서비스와 관리 스택 세 서비스 모두 healthy, daemon 1개.
    공개 URL 다섯 개 정상, `/health.release_sha`=R. #45의 Dagster healthcheck·`init`도 이 배포로 나갔다.
  - 옛 컨테이너 다섯 개는 `*-retired-20260928`(restart=no), 옛 daemon은 삭제, 옛 디렉터리는
    `/home/digitie/apps/kor-travel-airport.retired-20260928`. 옛 `n150-backup-cron.sh` crontab 줄은 지웠다(transport
    백업은 Manager standalone role `transport`·`transport_dagster`, 16:50·17:15 UTC).
  - Manager 개명 release(Manager #432 `e2d45d65`, target `transport`)를 설치했다. 옛 별칭 `airport`는 없다.
  - **배포는 새 디렉터리·project로만 된다.** 옛 이름을 쓰는 브랜치·손 스크립트는 main으로 rebase한 뒤 쓴다.
    retired 컨테이너를 `docker start`하거나 `-p kor-travel-airport`로 올리지 않는다.
  - 72시간 관찰 뒤 runbook "관찰과 정리"를 한다(그때까지 n150 prune 금지 — rollback 태그·retired 컨테이너가
    되돌리기 재료다). 되돌리기는 `rename-deploy-identity-server14.sh rollback`과 Manager 이전 release(`68cc1a93`) 재설치.

- 2026-09-28 `codex/port-coordinates-button-scroll`: 승인된 KOMSA 기항지 API를 주요 항구
  19개 명시 대상·지역/이름 정확 대조·DB 호출 예약/캐시로 연결 중이다. 항로 안내 점을
  항구로 쓰던 오류와 교통 탭 36px/버튼 44px 충돌을 수정했다. provider PR #9는 CI·
  두 독립 리뷰·live 확인 후 `2690f35`로 머지했고 의존성을 고정했다. admin WSL 단위
  111개·린트·타입·빌드·탭/상세 E2E 32개가 통과했다.
  Transport 전체 WSL/Docker·운영 검증·머지는 미완료다. 후속 지도/combobox/Map·Weather
  일치화 11개 항목은 현재 PR 완료 뒤 진행하도록 tasks에 기록했다.

- 2026-09-28 `chore/rename-deploy-identity-transport`: n150 운영 식별자 개명(ADR-010) 저장소 준비를
  푸시했다(PR은 아직 없음). PR #44(`835c0ec`)·#46(`50215b3`)·#47(`bdc9c02`)·#48(`a6edbd5`) 머지 위로 rebase했다. main이 더 움직이면 다시
  rebase한 뒤 PR·CI·두 적대적 리뷰를 거쳐 창 직전에 머지한다. n150 cutover는
  `scripts/rename-deploy-identity-server14.sh`와 `docs/runbooks/deployment.md` "운영 식별자 개명
  cutover"를 따른다. 창 전까지 옛 이름(`kor-travel-airport`, `/home/digitie/apps/kor-travel-airport`)이
  운영이다. 이 브랜치가 머지된 뒤에는 새 스크립트가 옛 디렉터리로 배포하지 않으므로 머지와 cutover
  사이에 다른 배포를 하지 않는다. `2da0579` 적대 검토(MED 1·LOW 7)를 반영했다: 창이 옛 스택을 멈추기
  전에 다시 빌드·Dagster gate하고 새 컨테이너가 같은 이미지 층으로 떴는지 본다(이미지는 `uv.lock`이
  아니라 빌드 시점 PyPI 최신을 받는다. containerd store에서는 cache hit 재빌드도 ID가 바뀌어 층으로 본다). 정리 단계까지 n150 prune 금지. 창 직전 PyPI에 운영(1.13.24)보다 새
  Dagster가 나오면 gate가 멈추고, 그때는 runbook "Dagster 버전이 다를 때"대로 고정한 새 R이 필요하다.
  3차 검토(`fdf6bee`·`a1e8e5f`, rebase 뒤 `16c3b01`·`237d37f`) 반영: 빌드 확인이 `… up -d --build`도 잡고, backups 목록을 못 읽으면
  멈추고, 대상 경로·URL을 셸 env에서 받지 않는다. **R 머지부터 `finish`까지 n150 freeze**(transport·
  관리 UI 배포, Map·Manager 빌드·rebind, prune 금지). 관리 UI는 #47 이미지
  `4580a5ca3c61`로 돈다. 공용 PostgreSQL prewarm(소유자 요구: 모든 DB)은 이 창 밖의 Manager 변경이다
  (runbook 전제, ADR-010 후속).

- 2026-09-28 16:49 KST: PR #47은 `bdc9c02`로 머지됐다. 후속 parking-radar DB 점검에서
  이미 공용 PostgreSQL `:11000/kor_travel_transport`를 사용함을 운영 DSN·SQL·웹앱으로
  확인했다. 공항 14·주차장 53·주차 관측 735,925·요금 규칙 32건, 최신 관측 16:45:03 KST다.
  기존 parking-radar live E2E 5개도 통과했다. 추가 DB 이전이나 복원·재시작은 하지 않았다.
  상세는 [공용 DB 운영 확인](runbooks/parking-shared-postgres-status.md)을 따른다.

- 2026-09-28 PR #47: Weather 정본 `c25642099`의 밝은 17rem 레일·파란 토큰·카드형
  헤더·컨트롤/표 밀도와 Dagster 요약 카드 치수를 적용했다. runtime 후보 `1db261e`를
  16:24 KST n150 UI에만 배포했다. 이미지 `4580a5ca3c61`, 컨테이너 `fa1001e6f2b3`는
  healthy/재시작 0/host network이며 보호 8개 컨테이너 ID·이미지는 불변이다.
  WSL/Docker admin 각각 109개·린트·타입·빌드, WSL UI 117개, Docker backend 283개를
  통과했다. James의 P2 두 건은 재현·수정·직접 재검증 완료, Popper 신규 지적 없음이다.
  운영 HTTPS E2E 414개가 136.39초에 통과했다(실패/제외/flaky 0). 일부 오류 UI는 mock이다.
  UI 소스도 백업 후 동기화했고 최종 증적 CI 통과 후 PR #47을 머지했다.
  후속 parking-radar 점검에서 공용 PostgreSQL 사용을 확인해 추가 이전은 하지 않았다.
  이번 UI PR에서는 DB·DSN·API·worker를 변경하지 않았다.

- 2026-09-28 14:35 KST PR #46 후보 `8ff8e7c541d05f46c5736a6f97edd762f2d7da9a`의
  shadcn/Weather형 관리 UI를 n150에 배포했다. 공식 Dockerfile 이미지 `cda9a4d83c3d`,
  UI 컨테이너 `efadbf197aca`가 healthy/재시작 0/host network다. API·worker·legacy
  frontend·gateway 등 보호 대상 8개의 ID/이미지는 불변이다. UI 소스도 백업 후 동기화했다.
  WSL/Docker admin 단위 각각 96개, WSL UI E2E 105개, 운영 HTTPS E2E 402개가 통과했다.
  live 결과는 121.24초, 실패·제외·flaky 0이며 일부 오류 상태 검증은 mock이다.
  James/Popper 독립 재리뷰 P0/P1은 없다. 최종 문서 CI와 PR #46 머지 상태는 GitHub에서
  확인한다. 버스 좌표·일반철도 운영 자료·오피넷/KRIC 실제 성공을 완료로 바꾸지 않는다.
  아래 기록은 단계별 이전 상태이며 이 항목이 최신이다.

- PR #46 James/Popper 독립 리뷰의 지적을 반영했다. 최대 확대에서도 겹친 장소는 선택
  목록으로 열고, 필터 선택 색·긴 항구 이름의 모바일 삭제 버튼을 보완했다. 항공편의 HTTP 200
  비정상 상태를 0편으로 표시하지 않으며 패널 재선택에도 호출 제한을 보존한다.
  장기 수집이 최근 30건 밖으로 밀려도 별도 STARTED 조회로 집계한다. 운영 Dagster 읽기 전용
  쿼리 응답을 확인했고 WSL 단위 96개·린트·타입·빌드가 통과했다. 수정 후 재리뷰·최종
  Docker·CI·n150 UI 전용 배포·live E2E는 진행 중이며 아직 머지하지 않았다.

- 2026-09-28 추가 요청으로 PR #46에 shadcn/ui(Base UI, base-nova)를 적용한다.
  로그인·지도 검색/필터·공통 다중 선택·보기 전환·상세 패널·Dagster·교통 현황을 전환했다.
  Tailwind v4를 기존 토큰에 연결하며 legacy parking-radar는 변경하지 않는다.
  WSL 단위 94개가 통과했고 운영 의존성 audit은 0건이다. 최신 E2E/리뷰/배포는 진행 중이다.
  WSL 전체 백엔드 최초 272 통과·7 실패·4 제외 중 7 실패는 `/tmp` 여유 공간 부족으로,
  전용 디스크 경로로 옮긴 백업 테스트 9개 재실행이 통과했다. Docker 백엔드는 283개 통과했다.

- 2026-09-28 후속 UI 작업 `codex/weather-inspector-markers` 진행 중이다. PR #44는
  `835c0ec`으로 머지 완료했다. Weather Dagster의 요약·실행 표·스케줄 펼치기와 지도
  우측 inspector를 적용 중이며 항구 DB 시간표·공항 명시 출도착·저장 주차를 연결했다.
  마커 단순화와 화면 밀도 기반 묶음, 노선 번호+이름, 통계 최초 실패 구분을 포함한다.
  초기 WSL 단위 90개·린트·빌드는 통과했다. 새 E2E·Docker·독립 리뷰·운영 배포·머지는
  아직 미완료다. 버스터미널 좌표는 없으므로 가짜 지도 위치를 만들지 않는다.
  이전 배편 수집/운영 worker와 공유 DB는 변경하지 않는다.

- 2026-09-28 12:48:45 KST 앞당긴 배편 수집 완료: Dagster
  `b5038bf4-698d-43d3-9ac4-2e8a4a54afde` SUCCESS, DB run 19304 success다.
  12:38:54~12:48:45 KST(591.20초)에 호출 280회·스냅샷 280개 저장·실패 0건을 확인했다.
  건별 저장 간격 중앙값 2.146초(최소 2.039/최대 2.674초)다. 10일 범위 저장은
  1,697→1,977/7,490 스냅샷이며 미수집 5,513개는 다음 배치로 남는다. 스냅샷은 운항 편수가 아니다.
  12:45 정기 회차는 대체했고 12:46에 원래 `45 */4 * * *` RUNNING으로 복원했다.
  원래 주기와 280회 상한은 그대로다. 오피넷 실제 성공은 사용자 지시로 이번 머지 범위에서 제외했다.
  main PR #45 통합 `c606505`의 독립 James/Popper 재리뷰는 P0/P1 없이 끝났고, WSL/Docker
  통합 50개씩·운영 HTTPS E2E 365개(90.25초)가 통과했다. 최종 문서 커밋 CI와 머지 상태는
  [PR #44](https://github.com/digitie/kor-travel-transport/pull/44)를 정본으로 확인한다.
  공용 DB 일시 장애 원인·오피넷·KRIC 인증·UI 변경은 후속이며 완료로 보고하지 않는다.

- 2026-09-28 12:33 KST 재확인에서 `/health` HTTP 200(약 0.495초), API·gateway healthy,
  컨테이너 재시작 0을 확인했다. 공용 DB는 별도 조치 없이 자동 복구됐으며 장애 전 run 19269와
  항구 749·터미널 27·선종 7행의 갱신 데이터·성공 summary가 모두 보존됐다.
  로그상 12:28:57 내부 서버 프로세스 종료, 12:29:12 재초기화, 12:30:56 redo 시작,
  12:31:02 redo 완료가 관측됐다. 최초 장애 원인은 미확인이고 장기 안정 검증은 남았다.

- 2026-09-28 12:29~12:33 KST 후속 상태 확인에서 새 운영 문제가 발생했다.
  `/health`가 40초 timeout 후 재확인에서 HTTP 500을 반환했고 API 로그의
  `CannotConnectNowError`와 공용 PostgreSQL 로그의 `database system is in recovery mode`,
  `redo starts at`를 확인했다. backend·API gateway는 unhealthy다. API와 공용 DB의
  컨테이너 재시작 횟수는 0이며 OOMKilled=false지만 DB 내부 프로세스 장애 여부까지
  부정하는 증거는 아니다. 초기 원인은 아직 미확인이다. 컨테이너 healthy만으로 복구됐다고
  판단하지 않는다. 공유 DB/다른 프로젝트는 변경·재시작하지 않았고 머지도 하지 않는다.
  아래 항구 수집 성공은 이 장애 **이전** 검증이다. DB 복구 후 영속성·API 응답을 다시 확인한다.

- 2026-09-28 12:27 KST 항구 기준정보 복구 검증 완료: Dagster
  `e0faedee-deb2-40e3-9080-4db5d92bd074` SUCCESS, DB run 19269 success다.
  12:27:13~12:27:21 KST에 항구 749·터미널 27·선박 종류 7행이 전부 갱신됐으며
  성공 summary의 파일 RustFS 저장 플래그도 1이다. 위치 파일의 대표 항구명 12개는
  전체 749항구의 좌표 확보를 뜻하지 않는다. 이 단회 검증은 끝났으므로 재실행하지 않는다.
  고속도로·주차와 별도 reference 그룹 1개/전체 최대 3개라는 기존 Dagster 동시 실행
  계약에 맞춰 helper의 모든 활성 작업 차단을 기준정보·유가 충돌 차단으로 좁혔다.
  요청 응답은 25초 timeout이었으나 고유 tag 조회로 생성된 작업을 찾아 재요청하지 않았다.
  최신 `f5e9bca` CI backend/frontend/admin도 통과했다. 배편 12:45·오피넷 16:00 검증은 남았다.

- 2026-09-28 12:07~12:12 KST 확인: API/worker를 포함한 8개 컨테이너와 8개 job이
  정상이며 `e04356a`의 backend/frontend/admin CI가 통과했다. 항구 기준정보는 여전히
  DB run 19085 failed이며 항구 749·터미널 27·선박 종류 7행의 마지막 갱신은
  09-25 03:01 KST다. 수정 후 실제 기준정보 수집 성공은 아직 확인하지 않았다.
  단회 Dagster 검증 helper를 준비했으나 첫 요청은 지원하지 않는 executionMetadata.runId로
  작업 생성 전 거부됐다. 스키마 확인 후 고유 tag 기반 중복 방지로 수정했으며,
  정기 고속도로 작업 실행 중에는 안전 검사로 시작하지 않았다. 항구 작업은 아직 미실행이다.
  배편 12:45 실행은 기다린다. 오피넷의 13:10:46은 보호 해제 시각이며, 현재 정기 cron
  `0 */8 * * *`의 다음 실행은 **16:00 KST**다. 보호 해제 직후 자동 실행으로 오인하지 않는다.

- 2026-09-28 11:29 KST 배치 2초 설정을 n150 worker에 적용했다. 코드 후보 `be85eac`,
  이미지 `9067afc613eb`, code-server ID `c504c2673e02`다. 실제 Settings에서 배치 2초,
  호출 상한 280, 공개 조회 30초, 오피넷 60초를 확인했다. API는 기존 `ff45aea`/`3b77ac7`,
  UI는 기존 `3b6d220`을 유지한다. API/UI/기타 제어부 ID·이미지·재시작 횟수·시작 시각 불변.
  daemon Compose start는 완료 후 제거된 dagster-migrate 의존성 검사로 실패했으며,
  기존 ID `0c29730d59e8`를 직접 start해 healthy로 복구했다. 8개 job과 전체 health 정상.
  WSL 전체 253/선택 PG 4 skip, 최종 변경 WSL·Docker 24개씩, 최종 이미지 Docker 전체
  257개와 migration 왕복/check, CI를 통과했다. James/Popper가 최종 후보를 승인했다.
  새 간격의 실제 정기 수집은 아직 시작 전이며 다음 12:45 KST 배편 실행에서 확인한다.
  운영 HTTPS E2E 365개가 모두 통과했다(실패·skip·flaky 0, 약 1.9분). 일부 UI 상태 검사는 mock이며
  이는 새 간격의 실제 provider 수집 성공을 뜻하지 않는다. 오피넷 성공은 여전히 미확인이고
  보호 해제는 13:10:46 KST다. PR #44 머지는 이 실제 수집 검증 이후 판단한다.
  `transport-pr44` 자동 확인은 배포 재실행이 아닌 수집 검증 단계로 갱신해 ACTIVE로 재개했다.

- 2026-09-28 배편 간격 조정: 사용자 승인으로 배치 전용
  `FERRY_TIMETABLE_COLLECTION_INTERVAL_SECONDS=2`를 도입했다. 사용자 실시간 조회 30초,
  배치당 280회·4시간 주기, quota 즉시 중단은 유지한다. 기존 배편 run 19180은 11:06 KST에
  280개 스냅샷 저장 후 success로 끝났다. 새 후보는 아직 운영 미반영이며 전체 WSL/Docker
  테스트와 독립 재리뷰를 진행 중이다. 이전 ff45 후보 worker 배포 스크립트는 새 후보에 맞춰
  갱신하기 전 실행하지 않는다. `transport-pr44` 자동화는 이 작업 동안 PAUSED다.

- 2026-09-28 10:53~10:55 KST 사용자 요청으로 배편의 실제 진행을 재검증했다.
  DB run 19180 저장 스냅샷이 253→256→257개로 증가했고 전부 해당 배치의 동일
  `collected_at=2026-09-27T23:45:50.634951Z`다. 구 worker의 실제 코드가 배치 시작
  시각을 각 스냅샷에 재사용하며 건별 commit함을 확인했다. 정지 상태가 아니라 실제
  저장 중이다. 실제 설정은 호출 상한 280회·최소 간격 30초·요청 timeout 15초·10일분이다.
  08:45 KST에 시작한 이번 배치는 간격만 약 2시간 20분이 필요하다. 257개 시점에서
  호출 예산은 최대 23회 남지만 종료 시각을 확정하지 않는다. 스냅샷 수는 운항 편수가 아니다.
  앞선 STARTED만 확인한 모니터링은 실제 진행 증명이 아니며 이후에는 저장 증가도 대조한다.

- 2026-09-28 10:46 KST 자동 확인: 배편 `6ec8cc3c-eefc-42f6-b567-6a189b5afa8c`가
  STARTED다. 다른 활성 실행은 없고 API/worker 모두 healthy,
  이미지·컨테이너는 기존 상태를 유지한다. 배포·수집 중단·추가 수집·머지는 하지 않았다.
  `transport-pr44` 자동 확인은 15분 간격으로 유지한다.

- 2026-09-28 09:26 KST PR #44 API 선배포를 완료했다. runtime `ff45aea`, n150 이미지
  `3b77ac7d588e`이며 운영 스키마는 `0015_fuel_statistics_priced`다. 전체 backend 소스
  체크섬과 provider pin을 검증했다. 기존 UI `3b6d220`, parking frontend와 Dagster 실행부·
  제어부는 컨테이너 ID/이미지/재시작 횟수/시작 시각까지 보존했다.
  09:27 HTTPS E2E **365개 통과**(127.8초, 실패·건너뜀·flaky 0). 별도 무재시도 실데이터
  통계 2/7/10일은 8.067/10.179/1.792초, 로그인부터 통계 표시까지 4.593초였다.
  320/375/414/768/1440px 실화면 차트와 넘침을 확인했다. 유가 7일 SQL은 partial index를
  사용해 heap fetch 0·235ms였으나 전체 API 조회의 지연이 모두 해소된 것은 아니다.
  **worker 교체·실수집 검증·PR 머지는 아직 미완료**다. 배편 Dagster run
  `6ec8cc3c-eefc-42f6-b567-6a189b5afa8c`/DB run 19180이 실행 중이고 스냅샷 완료 수가
  75→82로 증가했다. 이 실행을 중단하지 않는다. code-server는 기존 `148a471`이며
  실행부의 오피넷 60초 설정과 새 KRIC pin은 아직 반영되지 않았다.
  `.playwright-mcp/pr44-deploy-worker.sh`와 `pr44-deploy-worker-remote.sh`는 미실행 상태다.
  업로드 전과 daemon 중지 후 활성 실행을 각각 확인하고 없을 때만 worker를 교체한다.
  추가 리뷰 Gauss의 daemon 정지 실패 시 복구 누락·재개 health 미확인 P1 두 건을 수정했고
  모의 실행 8건을 통과했다. 운영 적용·실수집 검증을 뜻하지 않는다. API 선배포 복구는
  별도 모의 실행 3건을 통과했다. 아래 08시 배포 차단 기록은 과거 상태다.

- 2026-09-28 PR #44 `codex/query-collection-reliability`의 코드 후보는 `ff45aea`다.
  KRIC provider PR #6은 count 없는 실제 터미널 27/선박종류 7행 계약으로 범위를 제한한 뒤
  독립 두 리뷰·WSL 117개·CI를 통과해 `2cbe443`으로 머지했다. 소비 pin을 갱신했다.
  통계 deadline/lock, 유가 부분 index·정비 정책, 오피넷 60초 설정 정렬, 배편 개별 네트워크
  실패 격리를 구현했다. CI backend 253/admin 84/frontend 85, WSL 전체 244(선택 PG 3 skip),
  Docker PG 전체 247과 최종 수정분 67, UI Docker 84/85개를 통과했다. 최종 수정의 WSL
  추가 검사는 16개 통과/PG 2개 skip이며 PG 취소·DDL 잠금/복구는 Docker에서 통과했다.
  James(Halley)/Popper(Arendt)는 `ff45aea`를 P0/P1 잔여 없이 재승인했다.
  **n150 배포·live E2E·머지는 미완료다.** 이미지 적재가 300초 상한을 초과해 해당
  `docker load` 클라이언트 PID 1072812만 정확한 명령 확인 후 중단했다. 이미 적재된
  `85ff755` 기반 1.3MB 소스만 얹는 경량 빌드도 120초 상한 내 완료되지 않았다.
  08:18 KST에는 두 작업 프로세스가 없고 최종 운영 이미지도 없는 것을 확인했다.
  I/O pressure full avg10 약 46%, load average 최대 19.54로 공유 서버 부하가 높다.
  API는 기존 `1dd1868`의 정상 응답을 유지한다. daemon 중지·서비스 교체·0015 운영
  migration은 실행하지 않았다. 다른 프로젝트 컨테이너는 변경하지 않았다.
  n150 유가 일반 VACUUM은 180초 상한으로 중단됐고 index cleanup 없는 visibility/analyze는
  10.3초에 완료했다. heap fetch 244,958→36,917이며 전체 index 정비 완료나 안정적 지연 개선을
  뜻하지 않는다. KRIC 48시간·오피넷 8시간 보호는 그대로다.

### PR #45의 별도 Dagster 개선 기록(수집 배포 상태는 위 최신 기록 우선)

- 2026-09-28 `fix/dagster-healthcheck-exec-form`에서 Dagster 세 서비스의 healthcheck를
  exec 형식·`python -I`·`init: true` 계약으로 바꾸고, command에서 Dagster 서비스를 유도하는
  계약 테스트를 추가했다. 아직 미배포다. 반영은 `scripts/redeploy-dagster-services-server14.sh`로
  한다(`docs/runbooks/deployment.md` "Dagster healthcheck·init만 바뀐 반영"). 스크립트는 이미지
  고정 → 렌더링 비교·drift gate → GraphQL 확인 → daemon 정지 → in-flight run 대기(상한 1800초) →
  비교·gate·컨테이너 ID·daemon 정지 재확인 → 파일 교체 → Dagster 세 서비스
  `up -d --no-deps --no-build` 순서로 진행한다. 어디서 멈추든(SSH 끊김·출력 pipe 닫힘 포함) daemon
  컨테이너를 `docker start`로 되살린다. 되돌리기도 같은 스크립트에 옛 파일을 준다.
  당시 `.env.server14`의 `BACKEND_RUNTIME_IMAGE`는 PR #43 배포가 `ab25bf7b`로 바꿔 두었다
  (PR #43은 2026-09-28 `8a34f77`로 main에 머지됐다).
  전체 배포는 지금 대안이 아니다. `deploy-server14-remote.sh`의 `DAGSTER_POSTGRES_URL` 검사
  (`^postgresql://`)가 지금 env 파일(`postgresql+psycopg2://`)을 거부한다.
  transport-admin 배포도 `docker-compose.shared.yml`을 덮어쓴다. 이 브랜치는 #43 머지 뒤 main을
  merge했으므로, 이 변경이 머지된 뒤의 main에서 나온 배포는 새 probe를 유지한다. 그 전의 트리에서
  배포하면 옛 probe로 되돌아간다.
  2026-09-27 11:46Z~19:51Z code-server 정지 조사는 `docs/journal.md` 같은 날짜 항목을 본다.

- 2026-09-28 PR #43 `codex/transport-followups`는 backend `1dd1868`/이미지 `ab25bf7`,
  관리 UI `3b6d220`/이미지 `d187870`으로 n150에 배포됐다. DB 전용 최대 300역 다음 예정
  마커, 버스 빈 날짜/자정 경계, 모바일 전환 시 통계 차트 잘림을 수정했다.
  WSL/Docker·CI·두 독립 적대 리뷰와 최종 HTTPS E2E 365개가 통과했다(5.7분,
  실패·건너뜀·테스트 재시도 0). 실제 통계 수치·canvas, 1440/375px 화면과 불광역
  마커를 확인했다. 최종 증적 커밋 CI·머지 상태는 [PR #43](https://github.com/digitie/kor-travel-transport/pull/43)가 정본이다.
  최초 통계 timeout/429 실패 기록은 보존하며 원인 해결로 취급하지 않는다. 배포 직후
  일부 장소 목록 17~30초, 통계 13~21초 지연과 UI 교체 중 일시 중단은 후속 과제다.
  KRIC 실제 시간표 적재는 아직 0건이며 48시간·오피넷 8시간 보호를 유지한다.

- 같은 날 먼저 n150
  code-server의 709회 연속 health timeout과 repository RPC timeout을 확인했다.
  Dagster의 STARTED/STARTING/CANCELING 작업은 0개이며 실행 subprocess도 없다.
  같은 이미지·컨테이너 복구를 우선하고 KRIC 48시간 보호와 오피넷 8시간 제한은 유지한다.
  같은 이미지·컨테이너로 code-server를 복구해 8개 job과 daemon 정상 상태를 확인했다.
  오피넷 05:10 KST 배치는 화면 데이터 대기 timeout, 항구 기준정보는 `totalCount` 누락,
  배편은 네트워크 오류로 실패했다. 수집 복구와 제공기관 데이터 수집 성공을 구분한다.

- 2026-09-27 `codex/rail-timetable-integration` PR #42의 최종 런타임 `37c7ca5`를
  n150에 배포하고 HTTPS E2E 349개를 모두 통과했다(실패·재시도·건너뜀 0개).
  제공기관 실제 `body` 배열 파싱은 `python-kric-api` PR #7(`7af9f237`)로 수정·머지했다.
  역사 34행/휴일 시간표 344행의 인증 응답을 확인했고 추가 인증 재호출은 하지 않았다.
  transport에는 코드·시간표·운행일 테이블, 48시간 시도 제한, DB 전용 조회와 역 비교
  화면을 추가했다. 위치 파일과 정확히 연결되는 역은 500/1,108개다. 이 변경의
  1차 운영 후보 `66038ad`/UI `b22affb`는 배포·347개 HTTPS E2E를 통과했다.
  추가 실화면에서 역 17곳의 범위 밖 좌표로 용유 선택이 실패해 머지를 보류했다.
  KRIC provider PR #8(`edf6ba49`), 장소 API·UI 방어를 반영한 최종 후보는 `37c7ca5`다.
  공개 파일 1,108행, UI 65개 단위/18개 철도 E2E, 두 리뷰어 승인을 확인했다.
  최종 WSL backend 229개/선택 PostgreSQL 2개 건너뜀, 동일 배포 이미지의 Docker
  PostgreSQL 231개·Alembic check도 통과했다. 실제 용유 선택을 세 번 재검증하고
  1440/375px 화면에서 오류와 가로 넘침이 없음을 확인했다. 최종 증적 커밋의
  CI·머지 여부는 [PR #42](https://github.com/digitie/kor-travel-transport/pull/42)가 정본이다.
  운영 스키마는 `0014`이고 KRIC 인증 배치는 9월 29일 15:04:58 KST까지 보호 대기다.
  시간표·달력·코드 테이블은 아직 비어 있으며 현재 다음 예정 열차가 실제 적재된 것은 아니다.
  일반철도 TAGO provider PR #20(`9ed221e3`)은 머지했으나 현재 키 단일 진단이 HTTP 403이다.
  이용 신청 승인 또는 다른 원인 확인이 필요하며 추가 인증 재시도는 하지 않았다.
  16시 오피넷 정기 수집은 시작 페이지 시간 초과로 실패했다. 빌드 종료 후 같은
  운영 브라우저의 공개 시작 페이지는 2.37초에 복구됐지만 유가 재수집 성공은 아니다.
  8시간 보호를 유지하며 다음 정기 배치 결과를 확인한다.

- 2026-09-27 PR #41의 검색·지도·수집 화면을 n150에 배포했다. backend는 `3a6a1c3`,
  관리 UI는 `79f9181`이다. 배편 DB 전용 5항구 비교, 좌표 없는 항구 검색,
  유종별 가격 마커, 고속/시외버스 2탭·공항·고속도로·16개 수집 영역 메뉴를 추가했다.
  James/Popper는 P0/P1 없이 승인했고, 최종 운영 HTTPS E2E 331개(2.1분),
  WSL/Docker 관리 UI 52개·타입·빌드, PostgreSQL CI 180개가 통과했다.
  실제 가격 패널의 잘림은 운영 화면에서 발견해 별도 재현·회귀 테스트로 고쳤다.
  기존 parking-radar frontend와 Dagster 수집 컨테이너는 재기동하지 않았다.
  최종 증적 커밋의 CI·머지 상태는 [PR #41](https://github.com/digitie/kor-travel-transport/pull/41)이 정본이다.
  도시철도 다음 열차, 일반철도 운행편, 버스 지도 좌표는 아직 미연결이며
  전체 데이터 연동 완료로 취급하지 않는다. 상세 계약은 `docs/architecture/transport-journey-ui.md`를 참고한다.

- 2026-09-26 여객선 운항시간표의 PostgreSQL 저장 전환을 n150에 적용했다. 실행 코드
  후보는 `0d7d292`, Alembic head는 `0013_ferry_timetable_snapshots`다. 오늘 포함 10일을
  유지하고 4시간마다 최대 280건, 호출 간격 30초로 누락 날짜와 당일을 보충한다. 항구
  API는 저장 스냅샷을 먼저 반환한다. 수집 활성화·이미지·release 설정은 운영 환경 파일에
  영구 반영했다. 초기 Dagster run은 `16d839e6-e0e4-4d61-ad35-7d2a5c739614`다.
  749개 항구 전체 수집은 진행 중이며, 소청도(`SEA10010`)의 9월 26일~10월 5일 스냅샷
  10개와 실제 운항 149건을 확인했다. 마지막 날의 제공기관 빈 응답도 저장되므로
  빈 응답과 미수집은 구별해야 한다. 관리 UI는 로그아웃 캐시 경합을 보완한 `6613515`로
  배포했고, 이 버전의 CI와 James/Popper 재리뷰 및 n150 HTTPS live E2E 279개가 모두
  통과했다. 최종 문서 커밋의 CI·머지 상태는 PR #40에서 확인한다. 다음 운영 작업은
  전국 10일 범위의 누락 수와 수집 실행 결과 확인이며, 호출 제한을 낮춰 초기 수집을 가속하지 않는다.

- 2026-09-25 TAGO 고속·시외버스 provider(`python-datagokr-api` PR #18)는 두 독립 적대 리뷰의
  P1/P2를 모두 해소한 뒤 `472c353`으로 병합됐다. transport PR #39는 터미널 기준정보
  `bus_terminal_references`, 72시간 provider 호출 guard를 둔 Dagster 수집, 저장하지 않는
  실시간 시간표 API를 추가했다. 공개 backend에도 `DATA_GO_KR_SERVICE_KEY`를 전달하고
  여객선·버스 시간표 cache의 TTL/LRU 상한을 고정했다. 최신 James/Popper 재리뷰는 모두
  `APPROVE`다. 다음 게이트는 최신 CI와 n150 live E2E, PR 머지다.

- 2026-09-22 `codex/transport-experience`는 병합된 PR #36 (`46f29da`)에서 분기했다.
  교통·유가를 하나의 저장 통계 화면으로 통합하고, 고속도로·유가·수집 source 코드를
  사람이 읽는 명칭과 Apache ECharts 그래프로 바꿨다. 열차·도시철도와 배편을 독립 화면으로
  분리했고 배편 시간표는 사용자가 항구를 선택할 때만 실시간으로 읽는다. 지도는
  `digitie/maplibre-vworld-react@69abf9c`의 선언형 VWorld React 컴포넌트로 전환했으며,
  local tarball과 submodule revision을 함께 고정했다. Next.js 16.3.5/React 19.3.0
  migration, WSL lint·19개 단위 테스트·production build, backend 관리 API 계약 5건,
  깨끗한 Docker image build를 통과했다. James/Popper 적대 리뷰의 P1(통계 loading E2E
  문구, 지도 키보드 marker, 전체 철도 검색, 항구 요청 경쟁 상태)을 보완했다. 마지막
  Popper P1인 지도 기본 1,000건 공평 분배도 종류별 명시 요청으로 제거했다. 최종 재리뷰가
  지적한 넓은 범위의 대량 렌더링은 viewport bbox API와 `total`·`truncated` 안내, zoom별
  종류당 100/200/300개 예산(전체 최대 900개)으로 보완했고, VWorld 타일 오류는 장소 선택
  상태와 무관하게 화면 오류 상태로 노출한다. 항구 시간표의 서로 다른
  cache miss는 기본 30초 provider 보호 간격을 적용하며, 관리 proxy는 `Retry-After`를
  보존한다. API 39개, 관리 경계 5개, frontend 단위 19개, lint·type-check·production build,
  clean Docker build가 통과했다. keyboard marker provider 변경은 병합된
  `maplibre-vworld-react` PR #27에 포함됐다. Popper P2인 numeric 좌표 bbox index와 legacy
  `kind` 없는 목록의 균등 반환은 별도 성능/API 계약 task로 남겼다. 다음 순서는 수정 CI·최종
  재리뷰, n150 HTTPS live E2E, transport PR 머지다. n150의 오래된 checkout에는 Next 16
  `proxy.ts`와 충돌하는 legacy `middleware.ts`가 남아 있었고 첫 Docker build는 재기동 전
  안전하게 중단했다. deploy script가 archive에 없는 정확한 stale path만 제거하도록 보완한
  후보로 다시 CI·배포를 수행한다. 첫 live E2E는 Windows CRLF browser key의 trailing
  carriage return로 VWorld custom protocol이 fallback을 사용한 것을 발견했다. n150 env의
  line ending을 정규화해 WMTS HTTP 200을 확인했고, 느린 통계 E2E는 실사용 hydration을
  고려한 상태 기반 계약으로 보완 중이다. provider custom protocol의 fallback 오류도
  `vworld-tile-error` event로 화면에 표시해 타일 실패가 숨지 않도록 보완했다. n150의
  273건 live E2E가 발견한 제공 영역 밖 `200/XML FileNotFound`는 provider PR #28에서
  정상 fallback으로 분리했고, submodule·vendor tarball·SRI까지 새 revision으로 고정했다.
  실제 `200 image/png`가 로드돼도 MapLibre가 source-level error event를 내는 경우는
  provider의 fetch 실패 event와 구분해, HTTP status가 확인된 native 오류만 UI banner로
  올리도록 보완했다.
  `67d17a3` n150 배포본의 live E2E는 외부 VWorld tile 접근 실패 경고와 통계 6일 cold
  request의 단발 504로 267/273만 통과했다. 전자는 외부 공급자 접근 불가에도 fallback과
  명시 경고를 허용하는 지도 E2E 계약으로, 후자는 502/503/504의 제한 재시도로 보완했다.
  type-check와 frontend unit 19건은 재통과했고, 다음 순서는 수정 CI·n150 동일 SHA
  live E2E 재실행·PR 머지다.
  frontend clean install, type-check, 19개 unit test, Next production build가 통과했으며,
  다음 순서는 이 후보 CI·James/Popper 재리뷰·n150 273건 live E2E·PR 머지다.

- 2026-09-22 `codex/transport-map-view`의 Draft PR #36은 최신 원격 후보를 기준으로
  n150 live E2E에서 발견한 공개 gateway 재생성·통계 cache 후속 보완 중이다. 공개 268건
  HTTPS E2E는 전체 3일 통계의 cold read 504와 순간 DNS 해석 실패 2건으로 265건만
  통과했다. 원본 고속도로 관측을 5분 사전 집계로 읽고 시작 경계만 원본으로 정확히 보정하는
  migration `0010_transport_five_minute_stats`를 추가했다. 고속도로 수집은 최근 두 시간
  bucket과 이번 수집의 오래된 정정 bucket을 재구축하며 SQLite 테스트는 빈 집계에서 원본
  fallback을 사용한다. James/Popper
  적대 리뷰의 P1에 따라 cache miss를 키별 single-flight와 LRU 128개 상한으로 보완했고,
  정적 OpenAPI도 재생성했다. 서로 다른 cache key의 90일 집계 병렬 폭주는 전역 semaphore
  두 개로 제한했다.
  KRIC 철도 기준정보는 Dagster의 매일 03:00 KST due 평가와 마지막 성공 기준 48시간
  gate로 제한했고, 항구 시간표는 KST 날짜 범위·요청 병합·제공기관 429 음성 캐시를
  적용한 실시간 전용 조회로 유지한다. Docker 회귀 fixture는 운영 `DATABASE_URL`을
  읽지 않고, 명시적 `TEST_DATABASE_URL`과 안전 표지 없이는 PostgreSQL을 사용하지 않는다
  (운영 경로는 PostgreSQL 전용). 지도는 MapLibre 레이어·클러스터만 사용해 대량 DOM
  marker를 만들지 않으며, native 장소 목록으로 키보드·스크린리더 선택 경로도 제공한다.
  항구 전환은 진행 중 시간표 요청을 취소한다. 공개 gateway는 bind mount allowlist 변경 때
  전용 세 서비스만 강제 재생성하고, 저장 통계는 기본 60초 cache를 사용한다. 다음 순서는
  최신 SHA의 CI와 James/Popper 독립 재리뷰 → n150 재배포·268건 HTTPS live E2E → PR
  머지다.

- 2026-09-22 KRIC 인증키를 수령했고, 제공기관 권고에 맞춰 rail reference Dagster schedule을
  매일 03:00 KST due 평가와 마지막 성공 뒤 실제 48시간 gate로 변경 중이다. 인증 OpenAPI는
  전국 역·열차 반복 수집에 넣지 않는다. 공식 역사 코드 XLSX로 최소 파라미터를 확인했으며,
  오늘의 승인 operation 검증은 오류 envelope로 끝나 추가 재시도를 중단했다. 다음 허용
  시점에는 공식 sample 코드(`KR/1/135`, `01/A1`)로 operation별 한 번씩 재검증하고
  provider 오류 분류를 보완한다.

- 2026-09-22 `codex/transport-map-view`에서 주유소·역·항구 지도와 저장 장소 API를 구현 중이다.
  항구 좌표는 키 없는 해양수산부 항만가이드라인 CSV에서 RustFS 보관 후 연결하고, 시간표는
  실시간 요청만 허용한다. 다음 단계는 Docker/HTTPS UI 검증, 적대적 리뷰, provider와 transport
  PR의 CI·머지다.

- 2026-09-22 `codex/transport-dashboard-performance`은 n150에서 7일 통계가 약 3.9초,
  수집 상태가 30ms인 것을 측정했다. 대시보드는 빠른 저장 상태·돌발을 먼저 표시하고,
  통계는 독립 패널로 늦게 반영하며 60초 session cache를 사용하도록 보완했다. 느린 통계가
  수집 상태 화면을 가로막지 않는 Playwright 계약을 추가했다. Docker build와 n150 live
  E2E, CI·적대 리뷰 뒤 별도 PR로 머지한다.

- 2026-09-22 `codex/transport-admin-e2e-expansion`은 병합 뒤 n150 HTTPS UI E2E를
  260개 운영 행렬로 확장 중이다. 재현된 관리 proxy 10초 abort/`502`를 공개 gateway와
  같은 30초 timeout으로 보완했다. route-filter 통계의 public `504`에는 covering index
  migration `0008`을 추가했다. 두 적대 리뷰는 P0/P1 없음으로 결론냈고, P2로 받은
  공격 Origin CSRF 검증과 invalid concurrent index 복구 문서를 반영했다. n150 backend
  migration 배포와 260개 HTTPS live E2E(260/260, 2분 18초), backend/frontend/admin CI를
  모두 통과했다. 별도 PR #34는 Draft 해제·squash merge만 남았다.

- 2026-09-22 `codex/transport-admin` PR #33 후보 `92cb128`은 n150에 전용 API
  `12301`, Dagster `12302`, UI `12305`로 배포됐다. backend health SHA 일치와
  7일 통계 `2.50초`를 확인했다. HTTPS browser E2E가 발견한 로그아웃의 internal HTTP
  redirect와 Dagster CSRF 기대값을 보완 중이므로, 이 후속 패치를 CI·두 적대적 리뷰·live
  E2E에 다시 통과시킨 뒤에만 머지한다.

- 2026-09-22 `codex/transport-admin`에서 weather admin과 같은 인증된 server-side proxy
  구조의 transport 전용 운영 UI를 구현 중이다. 기존 `parking-radar` frontend/Compose는
  변경하지 않는다. 새 독립 Compose project는 public API `12301`, Dagster `12302`, UI
  `12305`를 사용한다. Manager ADR-48의 사전 정의된 monitoring 포트는 Prometheus
  `12102`, cAdvisor `12103`, Grafana `12104`이며, 이 전환과 n150 live E2E가 다음
  배포 게이트다.

- 2026-09-22 현재 `codex/shared-db-dagster`의 PR #32는 최신 후보를 n150에 배포한 상태다.
  외부 live E2E가 KREX 동일 관측 시각의 행에서 과거 `collected_at`을 읽는 정합성 문제를
  발견했다. 수집 성공 때 동일 행의 수집 run·원본 값·수집 시각을 갱신하도록 보완하고,
  WSL 회귀 검증을 통과했다. 이 후속 커밋의 CI, James/Popper 재리뷰, live E2E를 모두
  통과한 뒤에만 PR을 머지한다.

- 현재 후보는 `e8ad95f` 이후 적대적 리뷰 P0/P1을 보완하는 후속 커밋이다. Manager bootstrap PR #381이 병합·n150 재설치됐고,
  transport application/Dagster 전용 shared DB와 RustFS raw bucket이 준비됐다. legacy
  history의 final dump/restore·count/watermark 검증도 끝났으며 receipt가 배포 전제조건으로
  남아 있다. runtime은 Manager Weather 정본과 동일한 host-network로
  `127.0.0.1:11000` PostgreSQL과 `127.0.0.1:12101` RustFS에 접근한다.
- n150에 `e8ad95f`을 배포해 application/Dagster metadata migration, backend, code-server,
  webserver, daemon, gateway, frontend가 모두 정상 기동한 것을 확인했다. `/health`의
  release SHA가 후보와 일치하고, code-server/webserver는 loopback 전용, gateway는
  무인증 요청에 401을 반환한다. 이번 보완은 cutover candidate staging/n150 direct deploy,
  legacy rollback env 보존, gateway loopback bind, 공항 수집 advisory lock의 전용 connection
  소유권을 추가한다. 다음 한 작업은 이 후보를 배포한 뒤 CI·두 적대적 리뷰·live E2E를
  통과시켜 PR #32를 머지하는 것이다.
- 현재 브랜치는 `codex/shared-db-dagster`다. 운영 scheduler 분리, 3일 주기 철도·여객항구
  기준정보 Dagster job, RustFS 원본 참조, shared PostgreSQL compose overlay를 구현했다.
  `python-kric-api#3`은 CI와 두 적대적 리뷰를 통과해 `6ed5ace`로 병합됐고, pagination 보강 PR #4의
  `cd01fbc`를 transport가 고정한다. 그
  commit을 고정한다. 항구 시간표는 DB·raw response에 저장하지 않는 실시간 조회 계약이다.
  `python-kric-api#4`의 bounded pagination 병합 SHA `cd01fbc`를 고정했다. 여객항구 기준정보 job은
  Manager RustFS/DB bootstrap이 준비된 뒤에만 활성화할 수 있다.
- 최신 검증은 새 `python-kric-api@cd01fbc` 환경의 WSL backend 138개 통과/1개 live skip, 새 image와
  `0006` migration을 적용한 Docker backend 139개 통과다. shared overlay `docker compose config`와
  shell syntax 검사는 통과했다. 공용 DB 전환은 검증 없는 기동을
  금지하며, legacy history final dump/restore·count/watermark 검증과 Dagster metadata migration
  one-shot을 요구한다. 다음 작업은 provider PR #4 병합·pin 갱신, Manager의 transport app/Dagster
  전용 role·DB와 RustFS bucket bootstrap PR, 이어서 feature REST와 항구 실시간 시간표 endpoint 구현이다.

- 이 작업의 목표는 `kor-travel-transport`를 국내 여행용 통합 교통정보 라이브러리/API로
  운영하는 것이다. provider에서 데이터를 주기적으로 수집해 PostgreSQL에 저장하고,
  저장 자료를 외부 OpenAPI와 내부 통계로 즉시 제공한다.
- 현재 T-040 브랜치에서 `python-krex-api` 고속도로 소통·돌발과 최신
  `python-opinet-api` Playwright 주유소·유가 수집/저장/API/통계를 구현했다. WSL2
  백엔드 전체 테스트는 통과했다. 최신 보강에서는 DB 실패 실행의 durable 상태,
  RFC7807 OpenAPI 계약, 활성 live 소스의 실제 저장·최신성 E2E 검증을 추가했다.

- 기준일: 2026-09-20
- 최신 검증: 런타임 `f7987b2d8858e83b2a602ac70cdcd5b5a4902d6b`의 WSL/Docker
  PostgreSQL 백엔드 각각 130개, 프론트 각각 85개와 타입/build가 통과했다. n150 배포와
  공개 health SHA 일치, 설치 OPINET `39e7acc`의 초기 탐색/종료(지역 조회 0회)를 확인했다.
  유가 59,035건과 다음 07:05:20 KST 예약은 보존됐다. 배포 직후 WSL E2E 첫 주차 표시의
  timeout 실패(15개 통과/1개 실패)를 보존했으며, 이후 동일 SHA GitHub push/PR CI의
  backend/frontend/live-e2e는 모두 통과했다. 아래는 이 최종 검증에 이른 진행 이력이다.
- 작업 브랜치: `codex/transport-collection-openapi`, Draft PR #30.
  기존 검증 런타임은 `50c9cd42d2f7a071f216d815e9bbce94546383ca`이며 현재 후보는
  후속 OPINET `39e7acc` pin과 검색 문맥 API 설명·통합 회귀를 추가한 상태다.
  n150 최종 배포는 `15d46a9a223827c7732d984f73822fbe7e15712e`이며 공개 `/health`의
  SHA 일치와 DB 정상 상태를 확인했다. 이 배포의 런타임은 위 `50c9cd4`와 동일하다.
  형제 provider 수정 PR은 KREX #16(`adda287`), OPINET #18(`39e7acc`)이다. 앞선
  `1601ef3`의 실제 수집 후 최종 리뷰에서 지역 간 동일 UID 가격 소실 경로를 재현해
  provider의 전역 병합으로 보완했고 통합 의존성을 새 SHA로 고정했다. 통합 최종 리뷰의
  추가 P1을 `af26362`/`02545fe`에서 보완했으며, 소스별 DB transaction 격리를 추가해
  검증을 완료했다. 기존 candidate의 WSL 백엔드 전체 125개가 통과했고 격리 보완 후에는
  실제 PostgreSQL NOT NULL 오류를 이용한 집중 테스트 4개 및 최종 전체 128개가 통과했다.
  고속도로 소통/돌발의 독립 성공·backoff, skip 기록의 실패 은폐 방지, 유효 가격 없는
  OPINET 실패 처리, RFC7807 500 및 JSON 프록시 body timeout을 보강한다.
  수정 프론트 WSL 전체 80개/타입 검사/build와 Docker 80개 통과. 두 reviewer가
  `50c9cd4` 코드의 P0/P1 없음으로 판정했다. James는 코드 승인, Popper는 전국 유가
  운영 게이트 미완료로 최종 승인을 보류했다. Docker 백엔드 128개도 통과했으며
  해당 런타임의 최종 n150 배포도 완료했다. 배포 SHA를 고정한 WSL 공개 live E2E는
  15개 통과/1개 실패했다. 실패는 `opinet_browser.last_error=collection_failed`로,
  소스 준비 상태 검증에서 멈춰 후속 교통/유가 조회·통계 검증에는 도달하지 않았다.
  이후 승인된 복구 실행과 강화 E2E는 아래와 같이 성공했다. 최종 후보 배포/CI 검증 전으로
  PR은 아직 미머지다.
  n150 실제 첫 KREX 성공은 소통 8,370건·돌발 80건이고, 다음 주기 수집과 공개 통계까지
  확인했다. 이는 전국 OPINET 성공 증적과 별개다.
  사용자 승인으로 22:23:21 KST에 예외 OPINET 전국 수집 run 13556을 1회 시작했다.
  기존 상태는 보호 receipt로 백업했고 기존 오류를 삭제하지 않았다. run 13556은
  23:12:02 KST에 success 완료, DB 기준정보 11,807곳/가격 59,035건/양수 29,426건을
  새 세션에서 확인했다. 다음 예정은 9월 20일 07:05:20 KST로 확정됐다.
  강화 E2E `308b278`을 배포 SHA `15d46a9`에 고정한 실행도 16개 모두 통과했다.
  별도 최신성 점검에서 20:31 KST 공개 소통 API의 최신 관측은 19:52 KST로 남아 있었다.
  새 공급자 연결에서도 같은 응답 시각을 확인했다. 수집 성공만으로 실시간 자료가
  갱신됐다고 간주하지 않는다. 22:25 KST에는 관측이 22:20 KST로 갱신됨을 확인했다.
  추가 E2E 보강은 관측/저장 시각 모두 15분 이내·미래 60초 이내를 요구한다. 회귀를
  포함한 프론트 WSL/Docker 85개, 타입/build와 두 코드 재리뷰를 통과했다.
- 다음 한 작업: 두 리뷰어의 최종 운영 확인을 마치고 증적 문서 후보의 배포 SHA와 CI를
  정렬한 뒤 provider PR #16/#18 및 PR #30을 `kor-travel-transport`에 머지한다. 그 다음에만 KRIC
  provider 구현과 교통정보 확장 조사 문서를 시작한다.
- `digitie/kor-travel-airport`(구 `digitie/parking-radar`) PR #2~#28 모두 **MERGED**
  상태다. 이 세션에서 다룬 마지막 코드/운영 PR은
  [#28](https://github.com/digitie/kor-travel-airport/pull/28)(UI 밀도 개선,
  T-039)이다.
- **완료된 initiative**: shadcn/ui 전환 + 과거 자료 조회 기능 + Hallmark
  재감사/재설계(계획 `C:\Users\digit\.claude\plans\iridescent-finding-parasol.md`)
  + UI 밀도 개선(T-039, 별도 계획 문서 없이 직접 요청).
  T-033(shadcn 기반 도입)·T-034(button/card/table/alert/confirm-dialog 치환)·
  T-035(라우트 기반 앱 셸)·T-036(과거 자료 조회 기능)·T-037(Hallmark audit)·
  T-038(Hallmark redesign)·T-039(UI 밀도 개선) 전부 완료·배포·live E2E 검증까지
  끝났다. 현재 진행 중인 작업은 `docs/tasks.md`의 T-040이다.
  - **T-039에서 새로 배운 것**: (1) "레이아웃이 비효율적"처럼 모호한 사용자
    피드백은 코드만 읽어서는 특정하기 어렵다 — 브라우저 확장이 연결 안 될 때는
    Playwright를 라이브 사이트에 직접 붙여 스크린샷으로 확인하는 게 코드
    추측보다 훨씬 빠르고 정확했다(이번 세션 내내 `mcp__claude-in-chrome__*`가
    연결되지 않은 상태였다). (2) 좁은 화면에 여러 텍스트 필드를 압축할 때는
    테스트에 쓴 표본 데이터가 아니라 실제 운영 데이터의 최댓값(길이·구분자
    위치)을 반드시 확인할 것 — 청주공항의 짧은 이름으로 검증하고 끝냈다면
    인천공항의 13자 주차장명(`T1 장기 P1/P2/P3/P4 주차타워`)에서 서로 다른
    주차장이 구분 안 되는 실사용 버그를 놓쳤을 것이다(hostile review가 잡음).
    (3) 새 UI가 기존 공유 CSS 클래스(`.action-stack`)를 재사용하면 그 클래스가
    다른 컨텍스트에서 이미 갖고 있는 반응형 규칙까지 같이 상속된다 — 공유
    클래스에 새 용도를 얹기 전에 기존 모든 사용처와 각자의 breakpoint 규칙을
    확인할 것.
  - **T-038에서 새로 배운 것**: (1) Hallmark 감사 지적을 그대로 코드로 옮길 때도
    새 버그를 만들 수 있다 — `.control-band` 브레이크포인트를
    `max-width: 64rem`으로 고쳤다가 Tailwind `lg:`의 `min-width: 64rem`과
    정확히 1024px에서 겹치는 새 overlap 버그를 만들었다(둘 다 경계값 포함이라
    같은 값을 쓰면 항상 겹친다) — `63.9375rem`처럼 한 스텝 아래 값을 써야
    진짜 배타적 구간이 된다. (2) `aria-live`는 "속성을 붙이는 것"이 아니라
    "상시 마운트된 엘리먼트의 내용을 바꾸는 것"이 핵심이다 — 이미 최종 내용을
    가진 채로 마운트되는 엘리먼트에 `aria-live="polite"`를 붙이는 건 스크린
    리더 announce를 보장하지 않는다(브라우저/AT마다 다름). 이 실수는
    `history-view.tsx`의 기존(이미 hostile-review를 거친) 패턴을 그대로 베낀
    데서 나왔다 — "이미 리뷰를 거친 기존 코드"도 검증 없이 복제하면 안 된다.
    (3) 디자인 감사가 지적한 minor(예: "클릭이 하나 더 필요함")를 고치기 전에
    그 UI가 무엇을 보호하는지 확인할 것 — `/backup`의 기본-접힘은 UX 결함이
    아니라 인증 없는 파괴적 관리 UI의 유일한 상호작용 게이트였다. 이 세션은
    hostile review가 지적하기 전까지 이걸 놓쳤다.
  - **T-036에서 새로 배운 것**: (1) 계획서에 적힌 API 대상(`/v1/parking/history`)이
    실제로 프론트에서 전혀 안 쓰이는 걸 조사로 발견했다 — task를 시작하기 전에 항상
    "이 endpoint를 실제로 누가 호출하는지" 먼저 확인할 것, 계획 문서가 최신이라고
    가정하지 말 것. (2) hostile review 지적을 무조건 수용하지 말고 재현해서 검증할
    것 — Popper의 P0(`build_time_series` 앵커 버그)는 직접 재현해 실제 버그로
    확인했지만, James가 같이 지적한 `toDateKey()` 자체의 타임존 버그 주장은 5개
    타임존으로 직접 재현 시도한 결과 사실이 아님을 확인하고 그 부분은 고치지
    않았다(반대로 James가 지적한 `disabled` 범위 비교 쪽 타임존 버그는 진짜였다 —
    같은 리뷰 안에서도 finding별로 따로 검증해야 한다). (3) 상대(`days`) 조회용으로
    설계된 시계열 버킷 함수(`build_time_series`)를 명시적 날짜범위 조회에 재사용할
    때는 "버킷 배치 기준점"이 암묵적으로 "최신 관측 시각"에 고정돼 있는지부터
    확인할 것 — 수집 공백이 있으면 조용히 잘못된 기간의 데이터를 반환할 수 있다.
    (4) react-day-picker(mode="range")는 클릭 1번으로 `{from, to}`를 모두 채운다
    (같은 날짜로) — "선택 완료 시 자동 닫기" 같은 로직을 짤 때 `from !== to`까지
    확인하지 않으면 첫 클릭만으로 팝오버가 닫혀버린다(실제로 이 버그를 만들었다가
    되돌렸다). 또한 react-day-picker는 선택이 바뀔 때마다 day-grid DOM 노드를
    리마운트하므로, 첫 클릭 전에 캡처해둔 두 번째 버튼 참조는 첫 클릭 후 detached된다
    — 테스트에서 두 번째 요소는 항상 재조회해야 한다.
  - **T-034에서 `<select>`/`ResponsiveSection`의 `<details>`/daily-flight-overlay의
    토글·체크박스는 의도적으로 안 건드렸다** — 기존 테스트가 native DOM 구조
    (`getByDisplayValue`, `<summary>` 클릭+`open` 속성, `aria-pressed`)에 의존해서다.
    T-035에서 라우팅이 실제로 바뀌었고 `ResponsiveSection`/`mobile-disclosure`
    패턴 자체가 없어졌지만(각 라우트가 자기 콘텐츠만 보여주므로 접이식 섹션이 불필요),
    `<select>`는 여전히 native로 남아 있다(AppShell의 공항/주차장 선택) — 그대로 유효한
    판단이다.
  - **로컬 검증 시 반드시 `npx tsc -p tsconfig.test.json --noEmit`도 같이 돌릴 것**
    (기본 `tsc --noEmit`은 `tests/`를 제외해서 안 잡힘) — T-034에서 이걸 놓쳐 CI에서
    한 번 걸렸다(`frontend` job이 정확히 이 명령을 실행함).
  - shadcn CLI(`init`/`add`)가 `globals.css`/`layout.tsx`를 자동 편집할 수 있으니
    (T-033에서 겪음: 기존 `--muted`/`--accent`/`--radius` 덮어쓰기, Geist 폰트 주입,
    Tailwind Preflight의 헤딩 bold 제거) 새 컴포넌트 추가 때마다 diff를 재확인할 것.
  - **T-035에서 새로 배운 것**: (1) 데스크톱/모바일을 CSS-only 동시 렌더링(`hidden
    lg:block`/`lg:hidden`)으로 바꾸면 RTL 테스트의 singular 쿼리(`getByRole`/
    `findByText`)가 "여러 개 찾음"으로 깨진다 — `getAllBy*`/`findAllBy*`로 바꾸거나
    `within()`으로 특정 nav를 스코프해야 한다. (2) 이 저장소의 `live-e2e` CI job은
    PR별 preview가 아니라 **실제 n150 운영 배포**(`pr.digitie.mywire.org`)를 대상으로
    돈다 — 새 라우트를 추가하는 PR은 머지 전 CI에서 항상 404로 실패한다(PR #18/#20/#22
    전부 동일 패턴, backend/frontend만 통과하면 머지 진행). (3) live E2E의
    `collector-status.last_run.status`를 `"success"`로 단언하는 기존 테스트는 실제
    운영 스케줄러가 `success`/`partial_success`를 주기적으로 오가서 실패할 수 있다 —
    코드 문제가 아니라 실시간 외부 API(KAC/인천) 특성이다. 보통 다음 스케줄러 사이클
    (3분 이내)에 `success`로 돌아오지만, 2026-09-06 재검증 때는 13분·5사이클 연속
    `partial_success`가 관측된 적도 있다(`raw_response_count`는 3으로 정상 — 소스
    자체는 다 응답하지만 그 중 일부 lot이 간헐적으로 실패). 여러 번 재시도해도 계속
    실패하면 코드 회귀가 아니라 실시간 데이터 상태이니 이 단언을 느슨하게(예:
    `["success","partial_success"]`에 포함되는지) 바꾸는 걸 별도 task로 고려할 만하다
    — 지금은 손대지 않았다. (4) **hydration 타이밍 레이스**: 클라이언트 라우트 전환
    직후 곧바로 다른 요소를 클릭하면(예: 탭 전환 직후 "더보기" 클릭) 로컬의 빠른
    연결에서는 안 드러나다가 CI 러너처럼 지연이 큰 환경에서만 클릭이 조용히
    무시되는 경우가 있다 — Chrome DevTools Protocol
    (`context.newCDPSession(page)` + `Network.emulateNetworkConditions`)로 실제
    네트워크를 로컬에서 스로틀링해 재현할 수 있다. 이런 클릭은
    `expect(async () => { await el.click(); await expect(result).toBe(...); }).toPass()`
    로 감싸 "효과가 실제로 나타날 때까지 클릭 자체를 재시도"하게 만들어야 한다(단순
    `.click()` 뒤 단언만 재시도하는 것으로는 해결 안 됨 — 클릭 자체가 무효였으므로).
- 저장소 식별자가 `parking-radar` → `kor-travel-airport`로 개명됐다(PR
  [#15](https://github.com/digitie/kor-travel-airport/pull/15), ADR-007). 배포되는
  웹앱 브랜드/백업 파일명/쿠키 키는 계속 `parking-radar`다 — `CLAUDE.md` §1 참고.
  n150 앱 디렉터리도 `/home/digitie/apps/kor-travel-airport`로 이미 이동 완료됐고,
  이 세션에서 n150 컨테이너 실사(`docker compose ps`)로 재확인했다.
- n150 SSH 접근: 이 저장소를 여는 Windows 로컬 세션(Git Bash)에는 n150용 SSH 키가
  등록돼 있지 않다. **WSL(`wsl.exe -e bash -lc '...'`)에는 `digitie@192.168.1.14`
  접근이 이미 되어 있으므로, `scripts/deploy-server14.sh`를 포함한 모든 n150 SSH
  작업은 WSL을 경유해서 실행한다.**
- `docs/tasks.md`의 진행 중 백로그: `T-037`~`T-038`(Hallmark audit → redesign, 위
  initiative 참고). `T-029`/`T-031` 등 이전 세션 항목은 모두 완료·머지·live 검증까지
  끝나 있다.
- 운영 호스트 `192.168.1.14`의 별칭을 "server14"/"14번"에서 "n150"으로 통일했다(PR
  [#12](https://github.com/digitie/parking-radar/pull/12)). IP·실제 파일명은 그대로다.
- n150에 `vm.swappiness=10`을 영구 적용했다(`/etc/sysctl.d/99-parking-radar-swappiness.conf`).
  4코어에 load average 30대, swap 거의 꽉 참, 컨테이너 42개(대부분 다른 프로젝트) 상태였고,
  parking-radar 자체 문제가 아니라 호스트 공유 용량 초과로 판단했다. 근본 해결(코어
  증설/다른 프로젝트와 용량 조정)은 여전히 미해결.
- `scripts/n150-backup-cron.sh`를 n150의 crontab에 등록해(3일마다 03:00 KST) PostgreSQL
  dump 자동 생성을 활성화했다. dry-run으로 실제 백업 생성 확인 완료.
- PR #3(`T-030`) 검증 중 발견한 두 버그(krairport의 KAC HTTPS 스킴 버그,
  `parse_kac_fee`의 SCREAMING_SNAKE_CASE 필드명 버그)는 모두 수정·머지 완료.
  `docs/adr/004-*.md` "후속" 참고.
- PR #4(`T-032`)로 PostgreSQL이 `docker-compose.db.yml` 별도 스택으로 분리됐고, n150
  운영 데이터도 기존 named volume을 재사용해 실제로 마이그레이션 완료했다(백업 확보 후
  무손실 전환, `parking_snapshots` 56,039건 확인).
- PR #5(ADR-005)로 `/health`를 제외한 모든 백엔드 라우트가 `/v1` prefix로 이동했다
  (무-호환 clean-cut). RFC7807 에러 포맷 통일, `scripts/export_openapi.py` →
  `docs/openapi.json` 기계 정본 추가. hostile review(Popper)에서 발견한
  `RequestValidationError` RFC7807 미적용, `scripts/verify_cutover.py`의 target(n150)
  호출 버저닝 누락도 같은 PR에서 수정했다. `{data, meta}` envelope는 명시적으로 범위
  밖(ADR-005 "후속"). n150 배포·live 검증 완료(`release_sha=03bd6f3`).
- PR #7(ADR-006)로 공휴일 수집을 `python-kasi-api`(`kasi`)로 옮겼다. hostile review
  P0/P1 없음. n150 배포·live 검증 완료(`release_sha=986d64e`,
  `GET /v1/holidays/summary` 실 KASI 데이터 확인).
- PR #9(`T-031`)로 `test_cutover_guards.py`가 Docker 컨테이너 안에서
  `ModuleNotFoundError`로 깨지던 사전 버그를 고쳤다(`sys.path` 계산이 로컬 repo-root
  깊이를 하드코딩한 것이 원인). WSL/Docker 양쪽 `82 passed`.
- PR #10(`T-029`)으로 ADR-004의 마지막 범위(비행편)를 완료했다. KAC ODCloud
  (`FlightStatusListDTL`)는 krairport에 없던 endpoint라, 형제 저장소
  `python-krairport-api`에 `KacClient.flight_status_detail_raw_items()`를 새로
  추가했다(별도 PR [python-krairport-api#7](https://github.com/digitie/python-krairport-api/pull/7),
  커밋 `cbe4d13`). IIAC는 krairport의 기존 `iiac_raw_items`가 endpoint와 정확히
  일치해 라이브러리 수정 없이 전환했다. hostile review(Popper)가 지적한 rate-limit
  backoff 비대칭(비행편은 페이지 조회마다 즉시 호출되므로 5분 주기 수집보다 위험도가
  높음)을 반영해 `KrairportRateLimitError`를 `status: "rate_limited"`로 구분하고
  `upstream_rate_limit_backoff_seconds` 동안 캐시하도록 고쳤다. n150 배포·live 검증
  완료(`release_sha=9961579`, KAC(`GMP`)/IIAC(`ICN`) 양쪽 `/v1/flights/status`가 실
  서비스 키로 `status=success` 반환).
- 운영 원본(레거시, 재배포 금지): `digitie@192.168.1.13:/home/digitie/apps/parking-radar`
  — 여전히 구 unversioned API를 서비스한다. `scripts/odroid-status.ps1`은 의도적으로
  버저닝하지 않았다.
- 운영 대상: `digitie@192.168.1.14`
- n150 공개 포트 (T-032 이후): API `14001`, web `14002`, DB `14000`(loopback 전용, 별도
  컨테이너). live E2E 기준 URL: `https://pr.digitie.mywire.org`
- n150 외부 API URL: `https://pr-api.digitie.mywire.org`
- (해결됨, PR #15/#16) 예전에는 Windows 로컬 체크아웃의 `core.autocrlf`가 배포 스크립트를
  CRLF로 깨뜨려 매 배포마다 `sed 's/\r$//'`로 우회해야 했고, git이 두 스크립트를
  100644(non-executable)로 추적해 재배포 때마다 실행 권한이 초기화되는 문제도 있었다.
  PR #15가 `.gitattributes`(`*.sh eol=lf`)를, PR #16이 파일모드(100755)를 고쳐 지금은
  `scripts/deploy-server14.sh`/`scripts/n150-backup-cron.sh` 모두 추가 우회 없이
  그대로 실행된다 — 2026-09-06 세션에서 n150 재배포 후 `stat -c '%a'`로 `775` 확인,
  `n150-backup-cron.sh` 직접 실행으로 exit `0` + 실제 dump 생성까지 재검증했다.

## 다음 한 작업

PR #51의 추가 운영 게이트인 오피넷 약 48시간 노후를 읽기 전용으로 진단한다.
유가 수집 복구까지 범위를 넓힐지는 사용자에게 물었으며, 확인 전 새 provider 호출·
수집 job 실행·quota 초기화는 하지 않는다. 전체 게이트가 충족되기 전 머지하지 않는다.
최종 CI와 운영 상태는 PR #51·검증 runbook에서 확인한다. API `840f585`와 UI `55148d2`는
이미 배포됐으므로 전체 스택을 다시 올리거나 기항지 수집을 반복하지 않는다.

KRIC 철도 수집은 09-29 15:04:58 KST 보호 종료 전에 재호출하지 않는다. 현재 PR을
완료한 뒤 별도 PR에서 `tasks.md`의 지도 정보·combobox·Map/Weather 일치화 11개 항목을 진행한다.

ADR-010 개명과 #45 운영 반영은 완료됐다. 새 디렉터리·project만 사용하고 72시간
관찰 전 n150 prune은 하지 않는다. parking-radar DB도 이미 공용 PostgreSQL이므로
추가 이전하지 않는다. 공유 DB 장애 원인, TAGO 일반철도 HTTP 403, 버스 좌표 및
배편 전체 저장 범위 등 나머지 이슈는 백로그를 따른다.

## 확인된 사실

- 13번의 현재 서비스는 프론트 `:3000`, 백엔드 `:8000`에서 응답한다.
- 13번은 Docker를 조작하지 않고 `http://192.168.1.13:3000/api/backend` HTTP GET만 사용했다.
- 13번 수집기는 10분 주기, n150 scheduler는 configured 300초/effective 180초로 운영 중이며
  최신 strict 검증에서는 run `86`, `2026-08-22T07:21:03Z` 관측까지 성공했다.
- n150 PostgreSQL은 Alembic `0005_transport_query_indexes (head)`이고 n150은 Docker Compose로
  API `14001`, web `14002`를 제공한다. 주차 configured scheduler는 300초, effective tick은
  180초 tick과 120초 safety buffer다.
- HTTP fallback migration은 snapshots 38,946건/lot 44개 관측, reference lot 53개/legacy ID
  53개 상태로 운영되고, duplicate legacy ID는 0개다.
- 이전 T-039 검증 당시 n150 runtime은 배포 Git full SHA와 `/health`의 release SHA가 일치하며 API/web 포트 계약
  (`14001`/`14002`)을 지킨다. 2026-09-07 기준 `release_sha=e39f05b52e56d363eccf4a146c6271a4ad800cad`
  (=`main` HEAD, PR #28 squash-merge 커밋, T-039)이고, 외부 게이트웨이(`pr-api`/`pr.digitie.mywire.org`)
  양쪽에서 이 값과 정상 응답을 재확인했다(live E2E `15/15 PASS`, 새로 추가한
  `.lot-card-grid` 데스크톱-숨김 회귀 테스트 포함). 외부 게이트웨이가 응답하지 않을 때는 항상 먼저
  n150에 SSH로 직접 접속해 로컬 포트(`14001`/`14002`)를 확인해 "배포가 실패했는지" vs
  "게이트웨이만 문제인지"를 구분할 것(T-036 배포 때 실제로 겪은 패턴).

## 남은 운영 확인

- exact SQLite dump는 사용하지 않았으므로 raw response와 기존 collection run ID 보존이 필요하면
  별도 운영 export를 제공한다.
- 백업/복원은 별도 app auth가 없으므로 `pr.digitie.mywire.org` gateway/private ACL의 외부
  노출 제한을 유지한다.
- scheduler 실행 중 restore는 `409` 유지보수 창 응답으로 제한하고, n150 scheduler는
  `300/180/120` 계약으로 운영한다. 마지막 기능 release의 strict gate는 `7/7` 통과했다.
