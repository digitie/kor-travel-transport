# Manager 호스트별 Dagster instance 설정 소비 계약 초안

## 2026-10-27 최신 운영 상태

PR #139의 최종 CI·두 리뷰·머지 뒤 최신3691에서 Odroid Transport CS의 Manager a7 정본
read-only 소비·실제 내부 SHA·공식 배포 복구 경계를 수용했다. 공용 plane은 기존 c444이고
다른 소비자/호스트까지 수렴했다고 쓰지 않는다. [최종 원장](2026-10-27-integrated-production-rollout.md).
아래 구현·CI 정정·미배포 표현은 당시 이력이다.


## 문제와 소유 경계

Transport main `71a551ef7fa29957be018294363063e1870be011`의 공식 원격 배포는
`docker-compose.shared.yml`의 `KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG`를 소비한다.
값이 없으면 Manager의 tracked `config/dagster-shared/dagster.yaml`로 돌아간다.
Manager main `6dd65766d083dd6cfd52ffd1f608dcf69502c125`의 tracked 상한은 6이다.
실제 Odroid의 기존 상한 5를 보존하려면 문서에 숫자만 기록하는 것으로 부족하다.
새 code-server를 만들 때 daemon과 다른 instance 설정을 읽는 접점을 코드로 막아야 한다.
현재 n150 6 / Odroid 5 이외의 새로운 상한·수집 주기·서비스 활성화를 제안하지 않는다.

근거는 Manager559 선행 설계와 두 호스트 설치 준비 보고서다. 이 문서 작성에서
운영 값·파일·프로세스를 새로 조회하지 않았다. Manager API/UI 변경과 CPU 후보
Transport138은 별도 작업이며 원본 dirty 파일과 해당 브랜치를 보존한다.

## Manager와 합의한 읽기 계약

외부 consumer의 명시적 조회 명령은 다음 하나다.

```bash
sudo -n ktdctl dagster-instance-config show --json
```

성공 출력은 정확히 아래 네 필드인 JSON 객체다. 예시 값은 합성 값이다.

```json
{"host":"odroid","max_concurrent_runs":5,"path":"/example/manager-owned/dagster.yaml","sha256":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"}
```

- `host`: 기존 Manager current-host/운영 identity가 선택한 키. 임의 `--host` override는 없다.
  Transport는 기존 `targets validate --json`의 `targets.transport.host`와 같은지 검사한다.
- `max_concurrent_runs`: boolean을 제외한 양의 정수. Transport가 별도 숫자를 정하지 않는다.
- `path`: Manager가 검증한 정규 절대 경로. 개행·제어문자·Compose 보간/volume 구문이 되는
  입력은 caller에서도 거부하고, 외부 환경변수의 임의 독립 경로를 정본으로 채택하지 않는다.
- `sha256`: 전체 파일 bytes의 소문자 64자리 SHA256. digest16이 필요하면 prefix로만 유도한다.

`show`는 생성·서비스 변경이 없는 읽기다. 성공 exit0, 미설치/미준비/오염/권한 오류는
고정 오류로 exit2이며 stdout/stderr·원환경을 재출력하지 않는다. 기본 n150 6의 경로와
bytes는 기존 tracked 정본을 유지하고, Odroid 5는 정상 installer가 명시적으로 준비한
Manager 소유 statefile이 없거나 불일치하면 실패한다. consumer가 `prepare`를 자동 호출하거나
root env를 고치지 않는다. 설치되는 CLI 절대 경로·파일 mode 및 동시성 경계는 Manager559
최종 구현과 독립 리뷰에서 확인해야 하며 이 초안의 합성 경로를 실제 경로로 사용하지 않는다.

추가 합의: 기본6의 path는 기존 `/opt/kor-travel-docker-manager/config/dagster-shared/dagster.yaml`
trusted 설치 alias를 유지한다. 따라서 정규 path는 절대 경로·부모 이동/개행 금지이며
`realpath == literal`을 요구하지 않는다. Odroid5는 Manager의 content-addressed
`/var/lib/kor-travel-docker-manager/dagster-instance/<fullsha>.yaml`이다. root 소유0444·
동일 SHA 파일 overwrite 금지이고 상위 state root의0700을 유지하므로 일반 계정의 직접 읽기는
보장하지 않는다. CLI가 예상 호스트 bytes·전체 SHA·소유/mode를 검증한다.
Transport는 파일 읽기 권한을 넓히거나 별도 복사본을 만들지 않고 daemon의 bind mount에
Manager가 반환한 path를 전달한다. installer G lock은 기존 계약을 유지하며 external deploy 전체와
Manager 설치의 상호배제를 새로 보장하지 않는다. 교체 직전 show 재검증으로 감지 가능한 변경은 거부한다.

## 기존 접점과 최소 구현 계획

1. `scripts/validate-deploy-host.py`는 이미 원격 자기 IPv4·Manager registry·읽을 수 있는 env를
   검사한다. 이 단일 정본을 확장해 Manager show의 정확 네 필드와 target host 일치를 검사한다.
   기존 호출의 기본 성공/실패 동작은 유지하고 instance 결과를 내보내는 명시 모드를 추가한다.
   실패 시 Manager 원문·경로 입력·비밀을 오류에 섞지 않는다. subprocess deadline을 유지한다.
2. `scripts/deploy-prod-remote.sh`는 env source 이후, override 설치·Compose config/build 전에
   위 결과를 얻는다. 사전 환경의 instance 경로가 정본과 다르면 거부하고, 같거나 미설정이면
   정본 path만 `KOR_TRAVEL_DAGSTER_SHARED_INSTANCE_CONFIG`로 export한다. local Compose의
   기존 기본값은 개발 호환을 위해 남길 수 있지만 공식 deploy/prepare-cutover는 fallback하지 않는다.
3. runtime env·cutover env·rollback env에서도 같은 정본 path를 보존한다. 원 `.env.prod`를
   수정하거나 env 전체를 출력하지 않는다. 기존 release/image 고정과 rollback 범위를 유지한다.
4. 긴 build/drain 뒤 서비스 교체 직전 `show`의 host/path/SHA를 다시 확인해 처음 결박과
   다르면 거부한다. 이것은 동시 Manager prepare 전체를 잠그는 보장이 아니다. Manager installer
   lock/준비 정책과 bind mount의 inode 수명까지 포함한 지원 경계는 선행 Manager 계약으로 확인한다.
   실패한 최종 검증 뒤 잘못된 경로로 rollback이 실행되지 않도록 순서와 실패상태를 시험한다.
5. 운영 관리자 UI만 배포하는 `deploy-transport-admin-prod.sh`는 code-server 소비자가 아니다.
   해당 entry에 불필요한 instance 준비나 Docker 변경을 추가하지 않는다. release staging-only는
   서비스 교체가 없음을 유지하되 실제 remote deploy는 반드시 이 검사를 거친다.

제품 변경 예상 경로는 기존 두 scripts와 관련 `backend/tests/test_deploy_host_guard.py`,
`test_deploy_prod_remote_guard.py`다. 기존 shared-db contract 회귀를 함께 읽고,
`docs/runbooks/deployment.md` 및 필요한 shared-db 설명만 정합한다.
새 SDK·수집기·일반 배포 프레임워크·독립 상한 계산기는 추가하지 않는다.

## 검증 순서와 미완료 범위

- 합성 CLI로 정확 argv, unknown/missing/extra key, 잘못된 host, bool/0/음수 max,
  비정규 path/개행/보간 문자, SHA 오염, exit/timeout/JSON 오류를 거부하는 회귀를 먼저 만든다.
- 실제 원격 script의 source→show→export→config/build→재검증→up 순서 및 cutover/rollback의
  동일 path 전달을 fake command로 검증한다. stale env가 정본을 덮거나 Docker 변경 후에야
  검증하는 경로는 실패해야 한다. 원문 sentinel이 stdout/stderr로 나오지 않아야 한다.
- n150 6 / Odroid 5는 합성 fixture로 같은 계약을 확인한다. 실제 두 호스트의 daemon/code-server
  effective path·bytes digest 일치는 Manager559 설치 후 별도 승인된 운영 readback으로 수용한다.
- Linux 순수 회귀·정확 lock CI·독립 적대적 리뷰 2개를 마친 뒤 통합한다. 이번 초안은
  제품 구현·검증·배포 완료가 아니다. SSH·PG·build·서비스·수집·상한 변경은 모두 0이다.

Manager559를 먼저 준비/설치하고 외부 Transport caller를 그 계약에 연결하는 순서다.
실제 운영 변경은 Root의 Map 마무리와 후속 슬롯 지시 뒤 별도 수행한다.

## 구현 체크포인트 — 운영 미실행

기존 validator에 명시적 `--instance-config` 모드를 추가하고 duplicate/unknown/missing key,
boolean/비양수 max, host 불일치, 비정규·보간 path, full SHA 오염을 거부했다. 기본 registry 검사는
기존 호출을 유지하며 새 모드는 같은 host 검증 뒤 정확 show 명령만 실행한다.
공식 remote script는 source 뒤 정본을 결박하고 stale env를 제거한 runtime/cutover/rollback
환경에 같은 path를 기록하며 교체 직전과 rollback 전에 같은 네 필드를 다시 확인한다.
Compose·API·SQL·DTO·provider·의존성·실제 상한은 변경하지 않았다.

초기 합성 집중119개가 통과했다. 이후 명시적 subprocess check/import 정렬과 기존 shared-db
계약을 포함한 최종 집중121개가20.42초에 통과했다. validator/직접 시험3파일 Ruff도 통과했다.
시험은 기존 Python 환경에서 `--noconftest`로 해당 순수 deploy 시험4모듈만 실행했으며,
전역 PG fixture·전체 앱/정확 lock·Docker·운영 수용을 대신하지 않는다. 기존 환경에 Ruff가 없어
첫 Ruff 호출이 본문 진입 전에 실패했고 다른 기존 캐시의 Ruff를 사용했다. 설치는 하지 않았다.

Manager559 실제 최종 CLI pin·외부 caller의 독립 리뷰2·정확 lock CI·두 호스트 runtime 동등성은
아직 미완이다. PR은 Draft이며 merge/SSH/build/PG/서비스·실수집은 수행하지 않았다.

선행 `//` path를 `PurePosixPath`가 보존하는 경계는 별도 음성에서1실패/18통과로 재현했다.
원 체크포인트와 실패를 보존하고 이 입력을 명시적으로 거부했다. 정책·일반 alias 허용은 동일하며
최종 집중122개20.89초·Ruff3파일이 통과했다. 실제 Manager가 오염된 path를 반환했다는 주장은 아니다.


## 2026-10-27 합성 CI 회귀 정정

최신 registry60초를 합친 `4a33fee`의 CI는 기존 테스트가15·30초만 허용해
1실패/1273통과/2건너뜀으로 끝났다. 동일 실패를 비운영 격리 시험에서 재현했다.
검증을 느슨하게 하지 않고 세 호출의 정확한 명령·기한을 hostname15/registry60/show30으로
각각 고정한다. 실제 제품 코드와1MiB/16KiB 경계·full SHA 검증은 바꾸지 않는다.
새 head CI·독립 두 리뷰·운영 caller 적용은 별도 수용 전까지 미완이다.
