# Transport 수정 후보 live UI 추가 검증

- immutable transport runtime: `027a9ca1ef943d792278cc8a09964bb6e4ea5c44`.
- common Python: `430a9e9cd5429204579792b1d4f8e399366dcb2f`, UI source `9da1889` / `0.1.0-dev.2`.
- 2026-10-04 17:01–17:04 KST, 원 작업자가 CUA 브라우저로 실행했다.
- n150의 전용 Compose project `codex-transport-recovery-20261004`만 사용했다.
  운영 provider key·daemon·DB를 사용하지 않았다. 외부 실제 수집과 운영 RSS는 NOT_RUN이다.
- [첫 후보 원문](2026-10-04-transport-live-ui.md)의 로그인·메뉴·native 실패 링크·
  여러 viewport 검증과 결과를 덮어쓰지 않는다.

## 오래된 활성 실행

실제 Dagster metadata에 아래 세 상태를 만든 뒤 SUCCESS metadata fixture 35개를 추가했다.
`get_runs(limit=30)`에서 세 ID가 모두 제외되는 것을 Python assertion으로 확인했다.
SUCCESS fixture는 실제 수집 실행 성공을 뜻하지 않는다. QUEUED에 필요한 remote origin은
설치된 Dagster의 origin 객체로 구성했다. 이 객체는 테스트 fixture 전용이며 제품 코드에는 넣지 않았다.

| 상태 | 실제 metadata run ID | UI 표시 |
|---|---|---|
| QUEUED | `3c05d6c0-e9e5-49e8-afb1-e30d711c3020` | 대기 중 |
| STARTING | `83a31d37-1ff9-42e2-88f2-feca0b6c8445` | 시작 중 |
| CANCELING | `d0085a1f-7ef8-48a4-a794-0740604ff55b` | 취소 중 |

브라우저에서 최신 production bundle을 다시 읽고 세 상태가 모두 실행 표에 표시되는 것을
확인했다. 기존 synthetic STARTED `7149b6ca-43fa-4d4e-8d12-08ad17a89d08`도 최근 30건
밖에서 보이며 4시간 상한 초과에만 정체 의심을 표시했다. 실제 worker가 6시간 실행되었다는
증거로 세지 않는다. 요약은 최근 34건·성공 29·실패 1·정체 1·스케줄 12/12였다.

별도 `failure_probe` op가 실제 `Failure`를 발생시킨 native run
`6300f6ee-181f-4749-a706-0f703c3d8a97`의 실패와 STEP_FAILURE 요약이 표시되었다.
test job의 실패 계획을 제품 collector 재실행에 사용하지 않았다.

## 반응형·장애 복원

- 1440 요청 viewport(실제 DOM 1425)와 375 요청 viewport(실제 DOM 360)에서 body 가로 넘침 없음.
- 두 표 region은 `tabindex=0`. 모바일 실행 표 width 308 / scrollWidth 608,
  ArrowRight 입력으로 scrollLeft 0→40을 확인했다.
- 새로고침은 최신 확인 시각으로 갱신했다.
- project label 확인 후 전용 Dagster 컨테이너만 중지했다. 새로고침 때 한국어 조회 오류·
  다시 시도 버튼이 나타나고 마지막 34건과 12/12 스케줄이 유지되었다.
- 같은 컨테이너를 복원하고 다시 시도했다. 오류·버튼이 사라졌으며 확인 시각 17:03:54와
  대기 실행이 유지되었다. 운영 shared webserver에는 장애를 주입하지 않았다.

## 캡처와 SHA256

| 캡처 | SHA256 |
|---|---|
| [데스크톱](2026-10-04-transport-postfix-desktop.jpg) | `181CDF2208558E92D4569C1FC33747B33A7AD6379A49F754801CDBB68C4489B9` |
| [오래된 활성 실행](2026-10-04-transport-postfix-pending.jpg) | `4DF130A8B03E68E91DEA1984ED1699A3274997D9469633C12B771385D94B067F` |
| [모바일](2026-10-04-transport-postfix-mobile.jpg) | `418B576479109920B30412DA2FEB6F7F4856683D495C3D3388EBAE7BBAD67D49` |
| [조회 중단](2026-10-04-transport-postfix-outage.jpg) | `19FCFCC8904A6EE2571BE72F5578F733E99686AB83AB050D9F1306BD215F1011` |

## 동일 후보 PostgreSQL

격리 Compose one-off backend에서 최신 source와 common wheel을 설치했다.
`test_collector_recovery.py`, `test_dagster_definitions.py`, `test_dagster_runtime_dependencies.py`
35 passed / 21.16초. 앞서 전용 migration DB의 0023→0024→check→0023→0024→check도
통과했으며 이 수정 후보는 migration 내용을 바꾸지 않았다.
전체 CI·WSL 결과와 두 독립 재리뷰 판정은 별도 closure에서 기록한다.
