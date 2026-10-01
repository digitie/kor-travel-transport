# ADR-011: 백엔드·내부 식별자를 `kor-travel-transport`로 옮기고 사용자 노출 브랜드 `parking-radar`만 남긴다

- **상태**: accepted
- **날짜**: 2026-10-02
- **결정자**: agent + human
- **보완**: [ADR-007](007-repo-rename-kor-travel-airport.md)의 "브랜드 `parking-radar` 유지" 범위를
  사용자 노출 표면으로 좁힌다. [ADR-010](010-deploy-identity-rename-transport.md)의 후속 정리(임시 개명
  guard 제거)를 마친다.

### 컨텍스트

ADR-008·010으로 저장소·패키지·DB·role·Compose project·컨테이너·이미지는 `kor-travel-transport`가 됐다.
남은 옛 서비스 이름은 두 갈래였다.

- `kor-travel-airport`: 이미 실행을 마친 한 번짜리 cutover 스크립트 둘
  (`rename-deploy-identity-server14.sh`, `cutover-shared-db-server14.sh`)과 그 테스트,
  `deploy-server14-remote.sh`의 임시 개명 guard(ADR-010 §6이 정리 뒤 지우기로 한 것).
- `parking-radar`(ADR-007이 브랜드로 남긴 이름): 백엔드 `Settings.app_name`(OpenAPI `info.title`),
  백업 dump 접두어, 테스트 env `PARKING_RADAR_TEST_*`, CI·로컬 기본 DB 이름·계정, 쉬는 Compose 스택의
  volume·project 이름, 패키지 설명과 스크립트 docstring.

2026-10-02 n150 읽기 전용 조사: `kor_travel_transport` DB에는 서비스 이름을 담은 schema·role·table이
없다(`public` schema 하나, role `kor_travel_transport_app`·`kor_travel_transport_dagster_app`).
`parking-radar_*` volume도 n150에 없다. 다른 저장소(Map·PinVi·concierge·weather·geo)는 transport API
경로·이름을 참조하지 않고, Manager target·백업 cron은 이미 `transport`다.

### 결정

1. 서비스 정체성으로 쓰인 이름만 바꾼다.

   | 항목 | 전 | 후 |
   |---|---|---|
   | `Settings.app_name` / OpenAPI `info.title` | `parking-radar` | `kor-travel-transport` |
   | 테스트 env | `PARKING_RADAR_TEST_DATABASE`, `PARKING_RADAR_TEST_SQLITE_TEMP` | `KOR_TRAVEL_TRANSPORT_TEST_DATABASE`, `KOR_TRAVEL_TRANSPORT_TEST_SQLITE_TEMP` |
   | 로컬 기본 DB 이름·계정·DSN | `parking_radar` | `kor_travel_transport` |
   | CI 테스트 DB 이름 / 계정 | `parking_radar` / `parking_radar` | `kor_travel_transport_test` / `kor_travel_transport` (운영 DB 이름과 겹치지 않게 `_test`) |
   | 백업 dump·staging 접두어 | `parking-radar-`, `.parking-radar-` | `kor-travel-transport-`, `.kor-travel-transport-` |
   | 쉬는 DB 스택 volume | `parking-radar_parking_radar_postgres_data` | `kor-travel-transport_postgres_data` |
   | live 스택 DB·volume | `parking_radar_live`, `parking_radar_postgres_live_data` | `kor_travel_transport_live`, `kor_travel_transport_postgres_live_data` |
   | ODROID 비활성 marker project | `parking-radar-odroid-disabled` | `kor-travel-transport-odroid-disabled` |
   | 패키지 설명·스크립트 docstring·운영 주석 | `parking-radar` | `kor-travel-transport` |

2. 한 번짜리 cutover 스크립트 둘과 그 테스트, 임시 개명 guard와 그 테스트를 지운다. 배포 스크립트가
   옛 이름을 담지 않는다는 음성 검사는 남긴다. 과거 명령은 `git show 07d3848:scripts/<이름>`으로 본다.
3. 사용자 노출 브랜드는 그대로 둔다: 웹 `<title>` `parking-radar`, 메타 설명, 브라우저 저장 키
   `parking-radar:dashboard-selection:v1`과 쿠키 `parking-radar-selection`, 공개 hostname
   `pr.`·`pr-api.digitie.mywire.org`, 화면 디자인 문서·Hallmark stamp(그 웹앱의 브랜드를 가리킨다).
4. 실제 공항을 뜻하는 이름은 바꾸지 않는다(ADR-010 §2와 같다): `airports` 테이블·열·제약·인덱스,
   `/v1/airports`, `AirportSummary`, `airport_code`, `AIRPORT_CODES_CSV`, `airport_collection_job`과
   trigger `dagster_airport`, `kind=airport`, `krairport`, "공항 선택" 같은 화면 문구.
5. 이미 적용된 alembic 파일(`0001_initial.py` docstring 포함)은 고치지 않는다. 배포 migration gate가
   파일 내용을 본다.
6. 과거 기록(ADR-004·007·008·010 본문, journal, tasks-done, 당시 runbook 기록)은 고치지 않는다.

### 근거

- 정확성과 단일 정본을 호환성보다 앞에 둔다. 백엔드 이름이 저장소·DB·Compose와 다르면 운영자가 OpenAPI
  제목이나 dump 이름으로 다른 서비스를 찾게 된다. 외부 소비자가 없어 계약 파손 비용이 작다.
- 백업 접두어는 이중 패턴(옛 이름도 읽기) 대신 배포 때 n150 파일 이름을 한 번 바꾼다. 패턴이 하나여야
  목록·보존 개수·복원 대상이 한 규칙으로 정해진다.
- 브라우저 저장 키를 바꾸면 사용자의 저장된 선택이 한 번 사라지고, 화면 이름은 사용자 기억과 북마크에
  묶여 있다. 소유자가 사용자 노출 표면은 유지하기로 했다.

### 결과 (긍정)

- OpenAPI 제목, 백업 파일, 테스트·CI 설정이 저장소·DB 이름과 같아진다.
- 실행이 끝난 cutover 도구와 guard가 사라져 배포 경로가 단순해진다.

### 결과 (부정)

- 배포 직후 n150 앱 백업 디렉터리의 `parking-radar-*.dump`를 손으로 이름 바꿔야 한다. 하지 않으면 그
  파일들은 앱 목록·복원·보존 개수에서 빠진다(파일은 남는다).
- 옛 `.parking-radar-*` staging 파일은 새 코드가 청소하지 않는다(배포 runbook에서 손으로 지운다).
- 로컬·CI 외의 환경에서 `PARKING_RADAR_TEST_*`를 설정하던 하네스는 새 이름으로 바꿔야 한다.
- 다른 호스트에 남은 옛 `parking-radar_*` volume은 이름으로 다시 붙지 않는다(dump/restore로 옮긴다).

### 후속

- 배포 절차는 [deployment.md](../runbooks/deployment.md) "백엔드 내부 식별자 개명 배포 (ADR-011)"가
  정본이다.
- Manager `docs/docker-management.md`의 transport 복원 설명에서 앱 dump 접두어를 새 이름으로 고친다.
- n150의 ADR-010 정리 단계(은퇴 컨테이너·rollback 이미지·`.retired-20260928` 디렉터리)는 운영자가 따로
  실행한다.
