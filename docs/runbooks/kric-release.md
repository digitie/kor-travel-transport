# KRIC 저장 시간표 배포 게이트

## 적용 범위

PR #42의 `0014_kric_timetables`는 새 테이블 세 개를 추가한다. 기존 교통/주차 테이블의
삭제·초기화는 하지 않는다. n150(`192.168.1.14`)만 대상으로 하며 기존 parking-radar
frontend, 다른 프로젝트, 공용 PostgreSQL/RustFS 컨테이너는 재생성하지 않는다.

## 배포 전

1. WSL 로컬과 Docker PostgreSQL 테스트, 관리 UI 단위·타입·빌드·새 E2E를 확인한다.
2. CI와 James/Popper 독립 적대 리뷰를 통과한다.
3. Docker 전체 빌드 후보와 최종 후보의 `pyproject.toml`/`uv.lock`이 같을 때만
   이미 테스트한 의존성 레이어를 재사용한다. 최종 소스를 복사한 이미지 자체를 다시
   Docker PostgreSQL 테스트하고, 동일 이미지 ID를 n150에 옮긴다.
   이번 KASI 보정에서는 변경된 provider 하나만 머지 SHA `4259e574`로 명시 설치하고
   나머지 의존성은 재해석하지 않는다. `pip check`와 전체 Docker PostgreSQL 테스트를
   다시 통과해야 한다. Compose에는 이미지 ID를 강제 전달하며 실제 컨테이너의
   `.Image` 값도 대조한다. env-file의 태그나 health의 SHA 문자열만 믿지 않는다.
4. 기존 backend/code-server 이미지, 보호 컨테이너 ID, 환경 파일과 DB를 백업한다.
   DB는 custom-format `pg_dump` 후 `pg_restore --list`로 읽기 검증한다. 다른 백업을
   자동 삭제하는 보존 정책은 이 수동 배포 백업에 적용하지 않는다.
   2026-09-27 약 13.5GB DB에서는 기본 압축/600초 제한으로 백업이 끝나지 않았다.
   재시도는 `--compress=gzip:1`, 3,600초 상한을 사용한다. 환경 파일이 백업 원본과
   동일하고 기존 backend 및 `0013` 스키마가 유지됐는지 먼저 확인한다.
   생성 중에는 `.dump.incomplete`/0600으로 보관하며 dump 종료·목록 검증·SHA-256
   계산을 모두 통과한 뒤 기존 파일을 덮어쓰지 않는 방식으로 `.dump` 이름을 확정한다.
   실패·강제 종료된 파일은 정상 백업으로 인정하지 않는다.
5. Docker 빌드 로그의 config digest와 containerd의 실제 이미지 ID를 혼동하지 않는다.
   보존한 테스트 컨테이너의 `.Image`/`ExitCode`, 로컬·원격 `image inspect .Id`, 실제
   배포 컨테이너의 `.Image`를 대조한다. PR #42 검증 이미지는 OCI index
   `sha256:9b7c7ad397483a422d242fb1b6384454ed445d4c092eb03c030e628a20fc7cda`다.
   실제 UI에서 발견된 좌표 보정 후보 `37c7ca5`는 이 이미지를 기반으로 최종 backend
   소스를 재설치하고 KRIC provider를 `edf6ba49`로 고정했다. 새 OCI index는
   `sha256:148a471b33b42123c6135ba3b3d0e259f3846554b371fbd1e3374964d1851283`이며
   별도 전체 PostgreSQL 테스트 후에만 승격한다. 새 스키마 변경은 없으므로 `0014`와
   검증된 백업을 유지하며 원본 좌표를 직접 UPDATE하지 않는다.

## 적용 순서

- 환경 파일에 키를 넣을 때 `$`가 Compose 보간되지 않게 단일 인용하고 0600 권한을
  유지한다. 키 원문·환경 전체·인증 URL은 로그와 PR에 넣지 않는다.
- 9월 27일 인증 진단 요청이 있었으므로 배포 직후 인증 배치를 돌리지 않는다.
  `dagster_kric_timetable`의 명시적인 `skipped` 보호 기록으로 배포 시각부터 48시간을
  보수적으로 대기한다. 이 행에는 진단 후 제한 초기화라는 이유를 남기고 실제 수집 성공
  또는 시간표 적재로 계산하지 않는다. 실제 인증 배치는 이후 due 평가에 맡긴다.
- one-shot migration으로 `0014` 적용 후 backend만 새 이미지로 교체한다.
- 실행 중인 Dagster 작업을 강제 중단하지 않는다. 긴 배편 작업이 끝나면 daemon의 새
  실행 시작을 잠시 멈추고 나머지 실행이 종료됐는지 다시 확인한다. 종료된 뒤에만
  code-server를 교체하고 daemon을 재시작한다. webserver와 parking frontend는 유지한다.
  worker 검증 실패 시 이전 이미지 복구와 bounded gRPC health 확인 뒤에만 daemon을
  재개한다. 복구 실패·이미지 불일치·health 실패이면 daemon은 중지 상태로 두고 알린다.
- 전용 관리 UI 배포 스크립트는 transport의 gateway 두 개와 관리 웹만 교체한다.
- 배포 SHA·health·스키마·provider 상태·외부 호출 없는 철도 조회·운영 HTTPS E2E를 확인한다.
  초기 미연결/미수집을 운행 없음으로 표시하지 않는 것도 검증한다.

## 복구

`0013` 코드의 startup guard는 `0014`를 거부하므로 이미지 롤백만으로 충분하지 않다.
따라서 자동으로 전체 DB를 과거 백업으로 덮어쓰지 않는다. 문제가 있으면 KRIC 신규 수집을
먼저 비활성화하고 원인을 확인한다. 새 테이블이 비어 있고 다운그레이드가 필요한 경우에만
새 테이블을 별도로 보존한 뒤 `0013` downgrade와 이전 backend/code-server 이미지를 함께
복구한다. 기존 주차·배편 수집 데이터가 들어간 전체 DB를 배포 전 상태로 되돌리지 않는다.

이 문서는 절차이며 실제 배포 완료 증적은 `docs/journal.md`에 따로 기록한다.
