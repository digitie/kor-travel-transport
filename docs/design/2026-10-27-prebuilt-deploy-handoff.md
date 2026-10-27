# 사전 빌드 배포 자식의 즉시 거절 계약

## 문제와 범위

외부 controller가 일정을 중지하고 빈 실행을 확인해 state를 복사해도, 기존 공식
`deploy-prod-remote.sh`는 다시 빌드하고 최대1800초 기다린다. 그 사이 시작한 실행이
끝난 뒤 교체하면 부모가 복사한 state는 이미 과거 상태다. 관리자 공식 본문에도
`up --build`가 있어 같은 중지 구간에서 다시 빌드한다.

기존 `deploy`·`prepare-shared-dagster-cutover`는 보존한다. 새 `deploy-prebuilt`는
승인된 외부 controller 전용이다. backend 자식은 세 역할, 관리자 자식은 두 역할만
고정 image ID로 교체한다. 빌드·pull·마이그레이션 기동을 하지 않고 잘못된 입력에서
일반 배포로 돌아가지 않는다. 제품 코드·provider·DB 모델은 바꾸지 않는다.

## 부모의 순서와 책임

부모는 기존 Manager global lock→Transport release lock 순서, 소유 일정만 중지,
다른 일정 상태 보존, 공용 daemon RUNNING 계약을 지킨다. 빌드는 중지 전에 끝낸다.
실제 child 종료가 확인되기 전에는 lock을 반환하거나 복구 자식을 겹쳐 실행하지 않는다.

1. 원래 전체 instigator 목록을 새로 저장하고 소유 일정만 STOPPED로 검산한다.
2. run 다섯 상태와 실제 worker가 빈지 즉시 검사한다. 중지 후에는 기다리지 않는다.
3. 현재 CS의 전체 CID를 고정하고 helper의 `--state-fingerprint <CID>`로 원본을 검사한다.
4. 같은 CID의 `/opt/dagster/state/.`를 `docker cp -a`로 새 위치에 복사한다.
5. 복사본의 기존 `scan_tree` manifest를 만들고 원본 fingerprint를 다시 검사한다.
   복사 전후 fingerprint가 같고 복사 manifest가 아래 fingerprint의 내용 부분과 같아야 한다.
6. 이 실행만의 receipt를 배타 생성·fsync하고 bytes SHA-256을 고정해 자식에게 전달한다.
7. 자식이 실제 끝난 뒤 새 실행/worker probe와 `drain(seconds=0)`으로 복구 여부를 정한다.

자식 호출 전 `replacement=true`를 기록한 것만으로 실제 교체를 판단하지 않는다.
기존 r2도 실제 inspect 결과의 CID/image 변경 여부로 복구를 분기한다. 새 부모에서도
이 관측 계약을 유지하고 state가 바뀐 교체0 거절을 별도 회귀로 확인한다.
자식이 state 변경을 발견해 교체 전에 거절했다면, 실제 CID·역할 관측으로 교체0을
확인하고 현재 state를 보존한다. 바뀐 원본 위에 이전 복사본을 덮거나 그 복사본으로
CS를 재생성하지 않는다. 교체가 시작됐거나 종료/상태가 불명확한 경우도 부모가 새
관측으로 정산한다. 과거 복사본을 복구 근거로 자동 재사용하지 않는다.

## backend 자식 입력

승인된 staging·전체 candidate SHA·Manager 대상/env·NVMe·정본 instance 검사와
공유 release lock은 그대로 필수다. `deploy-prod.sh`의 기존 로컬 진입은 이 mode를
지원하지 않는다. controller가 공식 staging을 끝낸 뒤 공식 원격 자식을 직접 호출한다.

| 환경변수 | 계약 |
|---|---|
| `DEPLOY_MODE` | `deploy-prebuilt`; 운영 env를 읽기 전의 caller 선택을 보존 |
| `CANDIDATE_SHA` | staging과 같은40자리 Git SHA |
| `PREBUILT_HANDOFF_FILE` | 자식이 읽을 수 있는 절대 JSON 경로 |
| `PREBUILT_HANDOFF_SHA256` | 부모가 고정한 receipt bytes의64자리 SHA-256 |

기존 ROOT/INPUT 디렉터리0700을 약화하지 않는다. 별도의 root 소유0711 디렉터리를
만들고 비밀 없는 receipt만 root 소유0644로 둔다. helper는 경로의 symlink, 파일의
종류·소유 UID·정확 권한·nlink1, 읽는 중 변경, bytes hash를 검사한다. 디렉터리 이름과
파일은 실행마다 새로 만들고 배타 생성한다. receipt 원문·env·Docker stderr는 로그에 쓰지 않는다.

receipt의 구조는 다음과 같다. 표의 key는 기계 계약이므로 원문을 유지한다.

| key | 값 |
|---|---|
| `version` | `1` |
| `release_sha` | 전체 candidate SHA |
| `images` | `backend`, `frontend`, `dagster-code-server` 정확 세 key와 `sha256:<64hex>` ID |
| `schema_revisions` | 실제 운영 `alembic_version` 목록 |
| `instigators` | 새로 저장한 전체 목록; 각 행의 `location`, `repository`, `kind`, `name`, `status` |
| `state.source_container` | 실제 복사 원본 CS의64자리 CID |
| `state.manifest` | 기존 복사본 `scan_tree` 결과; 상대 경로별 내용·uid/gid/mode |
| `state.fingerprint` | 원본에서 helper가 출력한 `root`와 `entries` |

fingerprint의 `entries`는 기존 manifest 각 행에 `mtime_ns`, `ctime_ns`를 추가한다.
파일은 bytes·SHA-256, 디렉터리는 종류, symlink는 target을 보존한다. `root`에도
uid/gid/mode와 두 시각을 넣는다. symlink는 따라가지 않으며 특수 파일은 거절한다.
읽기 때문에 바뀔 수 있는 atime은 비교하지 않는다. 파일 내용은1MiB 묶음으로 hash한다.
`entries`에서 두 시각을 제외한 값은 `state.manifest`와 정확히 같아야 한다.
같은 bytes 재작성과 파일 추가 후 삭제도 ctime/디렉터리 시각 차이로 거절한다.

## 교체 직전 검사와 실패

준비 때와 실제 교체 직전에 receipt를 다시 읽는다. backend release tag와 frontend
기본 tag의 ID·arm64를 확인하고 backend/CS의 ID가 같아야 한다. 운영 backend에서
읽기 전용 transaction으로 Alembic revision을 읽고 고정 candidate image의 network
없는 정적 Alembic heads와 비교한다. migrate 서비스나 DDL을 실행하지 않는다.

실제 CS의 CID·Compose project/service와 RUNNING을 확인한다. 전체 instigator catalog를
검사해 소유 repository가 정확 하나이고 소유 일정은 STOPPED, 외부 일정은 원래 상태여야 한다.
전체 활성 run 조회는 `NOT_STARTED`, `QUEUED`, `STARTING`, `STARTED`, `CANCELING`과
`limit:1000`을 사용한다.1000개 도달·조회 오류·origin/tag 불일치·둘 다 누락·중복 location
tag는 거절한다. 한쪽만 있으면 그 값을 사용해 Transport 실행을 놓치지 않는다.
실제 CS `/proc`에서 `execute_run`·`multiprocessing.spawn` worker도 확인한다.

원본 fingerprint를 복사 시점과 비교한 뒤 일정·run·worker를 다시 검사한다. busy나
변경을 관측하면 sleep0·교체0으로 즉시 실패한다. 세 역할의 임시 Compose overlay는
image ID를 고정하며 `up --no-build --pull never --no-deps`로 세 역할만 선택한다.
정본 instance·plane 버전·합류 검사와 교체 뒤 health/location 검사는 계속 수행한다.
strict EXIT trap은 CS rollback을 실행하지 않는다. 부모만 종료와 새 상태를 확인해 복구한다.

strict가 남긴 `Config.Image=sha256:...`를 다음 일반 배포도 처리한다. 이 경우 container의
`io.kor-travel-transport.prebuilt-release` 전체 SHA와 `RELEASE_SHA`, 실제 `.Image`,
그 SHA의 로컬 `backend:rel-<sha12>` tag ID가 모두 일치해야 기존 tag 복구 경로로 들어간다.
임의 label만으로 이전 이미지를 신뢰하지 않는다.

## 관리자 자식의 별도 입력

관리자 공식 `REMOTE` 본문은 같은 `DEPLOY_MODE=deploy-prebuilt`와
`PREBUILT_ADMIN_WEB_IMAGE_ID`, `PREBUILT_GATEWAY_IMAGE_ID`를 받는다. 로컬 진입도
mode/ID를 검증해 SSH 인자로 명시 전달한다. 운영 env로 mode/ID를 덮지 않는다.
기존 staging·lock·보호 파일·승인 경로 검사와 두 역할만의 재생성 범위를 유지한다.

관리자 ID는 로컬 기본 tag의 actual ID·arm64·image `Config.Env`에 빌드된 전체
`TRANSPORT_ADMIN_RELEASE_SHA`를 candidate와 비교한다. gateway는 기존 공통 nginx
이미지이므로 candidate release를 요구하지 않고 고정 ID의 존재·arm64만 확인한다.
두 역할의 ID overlay로 `up --no-build --pull never --no-deps --force-recreate`한다.
CS를 교체하지 않으므로 과거 CS receipt를 받거나 state 검사에 재사용하지 않는다.

## 남은 경계

일정 STOPPED와 반복 조회는 원자적 launch fence가 아니다. 마지막 probe가 끝난 뒤
Compose가 교체를 시작하기 전의 수동 launch·이미 진행된 daemon launch 경합은 남는다.
파일 순회도 filesystem snapshot이 아니다. 이 변경은 장기 재빌드·1800초 대기를
제거하고 관측한 경합과 복사 뒤 state 변경을 거절하는 계약이며, 모든 launch를
원천 차단하거나 운영 데이터 보존을 새로 입증한 결과로 확대하지 않는다.
새 controller의 실제 소비·종료 정산·복구 검토는 별도이며 이번 변경은 운영 호출0이다.
