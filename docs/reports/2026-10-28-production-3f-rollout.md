# 최신3f 운영 빌드·배포 수용 체크포인트

이 문서는 저장된 빌드·이미지 검증과 `c051` 실패 후 원복, `r11` 소스 검토와 G 경합 사전 검사까지 반영한 배포 미완 초안이다. 문서 작성자의 추가 운영 호출은 없다. 실제 cutover·운영 공개 UI35·수집/백업 smoke·ARM 전체 job 측정은 아직 수용하지 않았다.

## 완료한 코드·격리 검증

- 이미지·stage·격리 검증 source는 `3f5160a0d5e0c246fa744864998a3fc805542ce4`다. 이후 관측한 main `8d80dd1f23601254fdfecdb344212ff7a89cf00c`은 문서 아래 8개 경로만 달라졌고, 문서 밖 629개 항목의 mode/kind/blob은 같다. 8d80 이미지를 새로 빌드하거나 CI를 통과했다는 뜻이 아니다. PR #154와 이미 머지한 PR #155의 제품 변경은 3f 이미지에 포함된다.
- PR #154 head `3fb7c3d`의 GitHub backend·frontend·transport-admin 세 check가 SUCCESS이며, 그 Git tree는 main3f와 같다. GitHub `live-e2e` check는 SKIPPED이며 이를 성공으로 바꾸어 쓰지 않는다. 별도 실제 격리 UI39 수용은 아래 근거다. 과거65a의 CI6 결과와 구분한다.
- exact3f 프론트엔드를 **새로 컴파일**한 뒤 같은 source의 격리 PG18/schema0036·실제 API·Next·브라우저에서39개가 통과했다. 이전3bf/65a Next 재사용 결과를 새3f 컴파일로 바꿔 쓰지 않았다.
- UI는 모바일·데스크톱, 기존32개와 유가 통계 D-1/D-6·누락일·안내창을 포함한39개다. 14.569초, API15·tile40, 초기 script hold8개와 정상 종료·소유 API/PG·volume·unit/cgroup·터널/C7 정리를 확인했다. 고정 합성 fixture의 가격·날짜·신선도는 운영 데이터의 검증값이 아니다.
- Manager는 Odroid `f368af3e` 공식 설치와 공개 UI12 수용·문서 PR #564를 마쳤다. n150은 같은 제품 `d1468213`를 유지했다. 원래 설치 후 CLI25초 timeout과 뒤이은 Transport 공식 stage의 필수60초 검사 성공을 구분한다. 40.166초는 stage 전체이며 CLI 단독 시간이 아니다.

## PR155 실측의 의미

[교통 저장 배치 운영 전 기록](2026-10-27-traffic-store-batched-prefetch.md)의 측정은 Linux amd64/WSL·PG18·고정 입력8,300개 관측의 **저장·commit 구간**이다. 같은 phase 안에서 원본·후보6회의 전체 행 digest가 같았고, client CPU·wall 중앙값이 약 93% 줄었다. 전체 Dagster job, 원천 fetch, 운영 ARM 또는 서버 전체 CPU가93% 줄었다는 증거가 아니다.

표본 RSS 중앙값은 신규·정정·원입력 재적용에서 약2.90/3.35/3.25MiB **증가**했다. 서버 RSS와 ARM 전체 수집 전후는 아직 측정하지 않았다. 수집 CPU 개선과 메모리 저감을 같은 완료 항목으로 묶지 않는다. 이번3f 체크포인트에서 이 성능 시험을 다시 실행하지 않았다.

후보 API의16개 수집 관련 설정은 격리 검증에서 OFF였다. 운영 수집을 중지했다는 뜻이 아니며, 이번 문서 작업이 운영 설정·기존 lock/fence·소유권 경계를 바꾸지 않았다.

## 완료한 빌드·이미지 내용 검증과 별도 plane 수용

정본 Manager를 통해 최신3f source stage가 정상 종료했고 Git source827개·보호 파일/환경과 기존 runtime 보존을 확인했다. 현재 서빙4d와 desired3f를 같은 것으로 취급하지 않는다.

**21:02:54Z 관측에서는 unit은 약22분, backend 단계는 약21분 진행 중이었고 전체 빌드는 미완료였다.** 고유 빌드 unit은 active/running, 마지막 phase는 backend building, 최종 result는 없었다. 이 관측만으로 backend 이미지 완성, frontend/admin 빌드 완료, unit 정상 종료나 배포 성공을 주장하지 않는다. 당시 source와 NVMe·정본 G→R·소유 builder 상한을 따른 T의 별도 운영 경로가 진행 중이었다. 다른 builder를 중지하거나 잠금을 우회하지 않았다.

이전 G 경합으로 실제 build0이었던 실행, 첫 prebuild 계약 거부와 보존 검사, source 재준비 이력은 남긴다. 후보 UI의 최초 mux 경로/API 종료 기록 실패와 첫 성능 SDK 준비 실패도 기존 기록에서 지우지 않는다. 제어된 후속 성공은 원 실패를 무효로 하지 않는다.

21:02:54Z의 위 기록은 당시 이력이다. 이후 원 빌드는 전체 7,196.311초에 timeout됐지만 backend와 frontend의 CLI 완료가 각각 확인됐다. 원 실패와 정리를 보존한 뒤, 완료된 두 불변 ID만 재사용하고 새 고유 태그의 admin만 후속 빌드했다. 후속 정상 종료·보호 서비스와 서빙 alias 보존·소유 builder STOP 및 상한/registry 복원을 수용했다.

| 역할 | 검증된 ARM64 불변 imageID |
| --- | --- |
| backend·계획된 code-server | `sha256:b33985ac88a463776f0787c47e81a0c446949a642691905fd5b9ec1faa05803e` |
| frontend | `sha256:0c709a880f6895b0fda80b49943cac29c8aef2e3ad15333c857f28566cb5a8fc` |
| transport-admin-web | `sha256:b0a107259117b8701a7afe18f47529bf219fbc59d5879b38d348bffc7adf643f` |

별도 network-none/read-only 소유 컨테이너에서 앱·migration 96개 파일, Common c289, Dagster 1.13.24, schema head0036, PG18 client를 확인하고 컨테이너·unit 정리를 수용했다. 이는 이미지 내용 검증이며 운영 DB0036 migration이나 실제 CS 교체 성공이 아니다.

공용 plane은 Root가 공식 Manager 경로로 별도 수렴했다. 두 서비스 healthy·잔여 drift0, 정본 bind/내용 a7d907, workspace 불변, 전체 catalog와 non-plane 컨테이너 보존을 수용했다. 실제 정책 변경은 global6→5, Geo10→1, Weather10→3, external_weather3→2·slow1, INFO→WARNING이며 storage/launcher는 같았다. 이 결과를 Transport 배포나 무중단·성능 개선으로 확대하지 않는다.

## cutover 실패·원복과 다음 소스의 경계

- `29f`: 2.710초에 baseline·pause·DDL·runtime intent 전 실패했다. 당시 예외 상세가 가려져 **원인은 UNKNOWN**이다. 뒤의 FD9 결함을 이 실행의 확정 원인으로 소급하지 않는다.
- `8b36`: 1.616초, prebaseline `release_R` 단계의 `fixed_guard_reason=fd9_in_use`를 확인했다. 이 실행도 native·DDL·runtime 변경 전이다. 이후 예약 FD9 소스와 격리 kernel 검증을 별도로 수용했다.
- `c051`: Transport 원 RUNNING 18개에 STOP mutation18·running0을 기록한 뒤 부모의 `official_command_nonzero`로 중단했다. 최초 부모 호출 소스와 후속 endpoint 재현에 근거해 PG drain 접속 실패로 분류하지만, 당시 원 stderr를 확보한 것은 아니다. restore mutation18·running18 기록은 있으나 부모 복구 후 검증에서 `ContractError`/`native_restored=false`를 남겼다. query·map·equality 중 세부 발생 지점은 **UNKNOWN**이다. 그 실패 원장을 성공으로 고치지 않는다.
- 후속 독립 읽기 두 관측에서 전체 47개의 원 ID·상태가 10초 간격으로 같고 Transport 18 RUNNING, 원 STOPPED·다른 location, 기존 다섯 역할 healthy·보호 대상·DB0035가 유지됨을 수용했다. 이는 실패한 부모의 원복 판정과 별도 증거다. migration/runtime intent는 없었다.
- 같은 보호 PG·같은 DB의 읽기 전용 `SHOW port` 재현은 `-p` 없는 연결이 기본 socket5432에서 exit2, 실제 Cmd/정본 포트11000을 명시하면 exit0임을 확인했다. `c051` 원 stderr는 저장되지 않았으므로 이를 되찾은 것으로 쓰지 않는다.
- `r9`는 보호 PG CID와 실제 Cmd 포트를 pause 전에 검증하고 psql에 명시한다. 기존 SQL·statement3초/lock0.5초/idle5초/connect3초/외측15초·drain1800초, FD9·복구 guard는 유지한다. 소스 두 독립 리뷰와 저자 순수 44개 검증은 완료했지만 **새 cutover 실행·배포 성공의 증거는 아니다**. 이후 fresh 읽기 전용 사전 검사는 `pg_command_contract`로 거절됐다. 실제 Cmd를 3인자로 한정한 parser 가정이 맞지 않아 후속 r10 포트 parser로 분리했다. 새 55aa는 launch·root·unit 생성0, native·DDL·runtime 변경0이며 Root가 r9 실행 권한을 중지했다.

- `r10`: 순수 62개 검증·소스 검토 후 fresh 사전 검사도 `pg_command_contract`로 거절됐다. 실제 Cmd 33인자에 들어 있는 GUC 이름을 분류한 별도 읽기 원장 `ce00`은 설정 15개 각 1회·단일 포트11000을 확인했다. r10 허용 목록에서 빠진 이름은 `pg_stat_statements.max` 하나였으며 30f5는 launch0이었다.
- `r11`: 그 이름 한 문자열과 launcher 교차 핀만 추가했다. 실제 이름·pair_index를 쓰고 설정값은 가린 33인자 fixture를 포함한 순수 65개와 J/W 두 소스 리뷰를 수용했다. 이것은 실제 PG 전체 속성·현재 native 상태나 운영 배포를 확인한 결과가 아니다.
- `r11`의 다음 fresh 읽기 사전 검사는 **2026-10-28 02:21:06–11Z** canonical G 획득에서 `ManagerMutationActiveError`로 끝났다. PG·원 47개 native의 현재 상태를 검사하는 본문에는 진입하지 않았고, 새 4999의 launch·root·unit 생성 및 native·DDL·runtime 변경은 모두0이다. 그 시점에는 잠금 소유자 정체가 UNKNOWN이었고 강제 해제하지 않았다. 현재 상태를 새로 통과했다고 쓰거나 이전 `95c18`의 기존 5개 역할·DB35 복구 수용을 이번 검사로 확대하지 않는다.

02:23Z의 후속 읽기에서 G 소유자는 별도 Transport 이미지 검증 unit으로 확인됐다. 02:24:58–02:25:12Z 관측에서 그 unit은 active였으나 그때 담당자·작업 진척·최종 결과는 미확정이었다. 중복 배포를 진행하지 않고 우리 4999는 launch0/HOLD를 유지한다.

같은 후속 관측은 기존 4d의 다섯 역할 CID·imageID·시작 시각과 healthy, DB0035, 공용 plane 두 CID·imageID·시작 시각과 healthy 유지를 수용했다. 이 관측은 컨테이너 내부 파일과 환경 전체를 다시 검산한 결과가 아니며, 원 47개 native 상태를 새로 통과했다는 증거도 아니다. `95c18`의 별도 원복 수용과 범위를 구분한다.

이후 사용자의 명시 승인으로 조율해 별도 작업 「transport와 weather 지도 UI 맞추기」가 Transport 최종 배포를 단일로 진행한다는 실제 응답을 확인했다. 이쪽 4999는 미실행/HOLD이며 G가 해제돼도 경쟁 배포를 시작하지 않는다. 상대의 SDK/web 검증 보고는 우리 독립 운영 검증이나 배포 완료로 세지 않는다. 다음 작업은 단일 담당의 실제 배포·원 47개 복원·UI 결과를 받은 뒤 별도 수용하는 것이다.

## 남은 실제 수용

- 완료: 세 후보 이미지·내용·소유 빌드/probe 종료와 정리. 위 불변 ID와 3f source의 수용 범위에 한정한다.
- [ ] native 전체 catalog·selector/state 두 ID·원 상태 capture, Transport 원 RUNNING만 pause, tick 두 관측·다섯 active 상태·물리 worker 및 별도 PG writer의 자연 drain 수용.
- [ ] 정본 prebuilt cutover와 실제 API/code-server/admin source·schema·포트·호환 health 검증. T01 API/CS 동일 설정 앵커와 T05 제한 rollback 정책이 같은 release에 포함됐는지 확인.
- [ ] 원 RUNNING만 원복하고 원 STOPPED·다른 location·공용 daemon과 보호 서비스 상태를 보존한 실제 결과.
- [ ] **운영 공개 UI35** 수용. 기존32개와 실제 유가 DTO·card/dialog·모바일 구조3개를 검증하며 격리39의 합성 가격/D-1/D-6 값을 운영에 복사하지 않는다.
- [ ] 기존 필수 수집/백업 smoke 및 자연 수집 성공·실패 안정성 수용. 백업 생성·다운로드·복원 smoke를 소스 검토나 이미지 probe로 대체하지 않는다.
- [ ] 실제 ARM 전체 job CPU·메모리·PG 비용 전후 측정. 비교 가능한 입력·실행 구간·다른 부하를 함께 기록한다.

현재 문서는 남은 항목을 완료 처리하거나 native helper를 변경·실행하지 않는다. 실제 실행·cutover는 T, 공개 UI와 자원 슬롯은 Root의 별도 검토 경계를 따른다. 코드·격리 시험 수용을 운영 배포 완료로 확대하지 않는다.

## 근거 지문

민감한 원장은 저장소 밖에 보존하고 여기에는 식별 지문만 남긴다.

| 근거 | SHA256 |
| --- | --- |
| exact3f fresh Next build | `96c279d4fd3de38186f961f7972dba577bb5daaed8c3a1fe7cdb942588fdac3b` |
| exact3f 실제 격리39 | `b4875de6ca68e07d8aa0e78455612ca6733a9c0f32642ebafd5c4ebecc4370ac` |
| 격리39 독립 실제 수용 | `e04d1459bb78575e6c00346549edfbb5d639c14a25cad651270780da8c9e4c0b` |
| 최신3f 공식 stage와 보존 | `13e66c9a039f77b8eee617dfebae3858c95c1d4b5c811b2939e4066e125fa210` |
| 21:02:54Z 미완 빌드 관측 | `5a2fd0205d84ee571f7c46c05ced0cdce5ef029bf50745eec770b85d2268409d` |
| PR155 저장 실측 raw | `b9d501f3aff0574c68f633b81befbfde59a830a209c6a35c939c17c73201bc08` |
| PR155 독립 실측 검산 | `7554c83f92098f29fe6ee09c6680ff40748ac74f944546770c33eb8c90462f8f` |
| main 8d80 문서 밖 629 동등 | `5e516ba4cecc157eaf160f965faa1d3b96c187d3cf508cb4a9e63c87b3abf90b` |
| 후속 빌드·불변 세 이미지 수용 | `ed33ed77dbbf1f568f7af22ae7c764d95364d33a93aa4725c0ea08f76f51d44d` |
| 이미지 내용·소유 probe 정리 | `8e697a24c383d903e222cfc0d8587419d32fabd64a2e08a9509403d4370487b8` |
| Root 공용 plane 수용 | `02becfef01dc92ba46487102181ab08416aafddbf5568d29d832ae027ef52e8f` |
| c051 실패·원복 원본 보존 | `ec312cefc506bf8acc74142ac1a65d6765e8cea30bcbd5c05a050055421ddbca` |
| 별도 전체 47 원복 관측 | `95c18a37d0682d8e126e9f0d3836908a1ec538f3bd8137a15c4853b6e22ebfa0` |
| PG 포트 읽기 전용 재현 | `37b338e110096db6ccacc08934ee9a45e06505defe4620a640616e175901e233` |
| r9 소스·순수44 검증 결박 | `2697dead40ec313e25f5bd8957f7ef044240305ce695d86563aac32a43aa79af` |
| r9 fresh 사전 검사 차단·launch0 | `366d47ec49ea5e989e24ee6103bd2acf082b40bf4566a0d96e5cb1416742ef48` |
| r10 fresh 사전 검사 차단·launch0 | `d149832b13c3c3b98d70df8a80062cc12737bbce809348b119acfac783cc427c` |
| 실제 PG GUC 이름·pair_index 분류 | `ce00c5ee45780f28a902b36aa3cd7898f7820d53066bca72755e9fe2963acead` |
| r11 순수65 원장 | `9e650e02d0117993d7b5f02402c2ba53c0bdfc103d79f18b5d9127249e6992d4` |
| r11 독립 소스·순수65 결박 | `860fc5d909e1686db00efb746d79dc418b1a3eb5c872b70ea21312fce8470384` |
| r11 fresh G 경합·본문 미진입 | `23b695907b4474df5470b671d4b8b638a4834ef13ecd074a8b278ee4664bf0b6` |
| 후속 G 소유 검증 unit 식별 | `2a06d09a5e337daaca833f011cce4ba316cccdbf375b7e577ebfaef86623b0c4` |
| 기존 4d 다섯 역할·DB35·plane 후속 관측 | `747292c4c59e479dff22af50ecdd0ce2e7618aff8c22f10f5c9fa3bea6b515f0` |
| 단일 최종 배포 담당 조율 수용 | `aeb73ba00d20622d938588794bc3f41de398aa7ba2e47b0e37237fb7c2ce55aa` |
