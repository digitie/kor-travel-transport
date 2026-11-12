# 정상 이미지 빌드 진입점

## 범위와 정본

이 진입점은 clean tracked Git 소스에서 이미지를 산출하는 B1·B2·B3의 소스 구현이다.
운영 적용은 하지 않는다. 기존 [배포 런북](../runbooks/deployment.md),
[ADR-014](../adr/014-odroid-host-and-deploy-host-flag.md)와
[prebuilt handoff](2026-10-27-prebuilt-deploy-handoff.md)가 실제 역할 선택·상태·스키마·적용의 정본이다.
Manager SDK508의 기존 Transport core/public/admin 역할 지원을 재사용한다.
빌드 receipt를 운영 handoff나 SDK current/pin 대신 사용하지 않는다.

## 실행

Python3.12와 Docker/Buildx를 선택한 격리 Linux 빌드 환경에서 실행한다.
repo는 canonical GitHub HTTPS origin의 전체 소스이며 clean HEAD를 사용한다.
SHA와 tree는 검토 대상의 전체40자리 값이다. branch 이름·HEAD 같은 이동 참조는 받지 않는다.
output은 repo 밖의 새 디렉터리여야 한다. CLI는 설치·fetch·clone·SSH를 대신 실행하지 않는다.

```bash
make image-build BUILD_OPTIONS="--repo /work/transport --revision <40자리SHA> --expected-tree <40자리TREE> --role transport-admin-web --architecture arm64 --output docker --output-dir /work/build-output/new --public-inputs /work/private/public-inputs.json"
```

입력 파일은 소유자만 읽게 두고 출력과 함께 공개하지 않는다. --public-inputs - 로
stdin JSON도 받는다. 키·URL의 실제 값은 shell 인자나 make 변수에 넣지 않는다.
NEXT_PUBLIC 값은 웹 산출물에 포함될 수 있지만 빌드 로그·receipt에는 원문을 남기지 않는다.
고정 옵션 외 임의 Docker 옵션·tag·secret·push는 받지 않는다.

| 옵션 | 의미 |
|---|---|
| --role | 아래 역할을 반복 선택. 중복 역할은 거절 |
| --architecture amd64 또는 arm64 | 단일 Linux architecture. 쉼표 다중 값은 거절 |
| --output docker | 정상 docker build의 iid와 실제 image inspect 검산. 로컬 load |
| --output oci | 정상 Buildx OCI export. manifest/config/layer hash와 실제 config ID·architecture 검산. load/push 없음 |
| --public-inputs | 역할별 허용 JSON. 값 대신 공급된 값의 SHA-256 기록 |

| 요청 역할 | 실제 이미지와 Dockerfile | 허용 public 입력 |
|---|---|---|
| backend, dagster-code-server, migrate | 동일 backend 이미지, backend/Dockerfile | 없음 |
| frontend | frontend/Dockerfile의 production runner target | NEXT_PUBLIC_API_BASE_URL, NEXT_PUBLIC_API_PORT |
| transport-admin-web | 관리자 Dockerfile runner, repo root context·공유 frontend 유지 | NEXT_PUBLIC_VWORLD_API_KEY, NEXT_PUBLIC_TRANSPORT_DAGSTER_URL |
| dagster-gateway | backend/Dockerfile.dagster-gateway | 없음 |

migrate는 이미지 별칭일 뿐이며 컨테이너나 migration을 실행하지 않는다.
관리자 transport-api-gateway는 기존 외부 nginx 이미지 선택 계약이고
위 Dagster gateway와 다르다. 새 로컬 recipe를 발명하거나 같은 이미지로 치환하지 않는다.

## 소스·입력·실제 이미지 결박

한 번 생성한 tracked archive의 모든 Git blob/실행 mode와 gitlink SHA를 검산한다.
gitlink는 기록만 하고 재귀 checkout하지 않는다. ignored 환경 파일·설치 cache를
작업 트리에서 context로 복사하지 않는다. canonical origin/HEAD/tree/dirty 상태와
context의 bytes·uid/gid/mode·inode·ctime 등을 매 빌드 전후 다시 확인한다.
같은 bytes 재작성도 거절한다. filesystem snapshot이나 악성 Docker daemon 격리 보장은 아니다.

현재 production Dockerfile의 literal COPY 및 dockerignore로 복사 파일 목록·SHA-256을 산출한다.
내부 COPY --from은 Docker 단계가 처리한다. 지원하지 않는 변수·glob COPY나 dockerignore
구문은 추정하지 않고 거절한다. 수량은 현재 tree에서 계산하며 예전909/298/263을
새 소스의 고정 기대값으로 쓰지 않는다. 공급된 public 입력 hash와 Dockerfile 소스가 결박된다.
미공급 ARG 기본값은 해당 Dockerfile의 의미다. 필요한 운영 입력의 정본/현재값 선택은
호출자 책임이며 wrapper가 읽거나 바꾸지 않는다.

정상 build 결과의 실제 immutable image ID, Linux architecture, OCI source URL의 .git,
전체 revision/tree/역할/COPY/input hash label과 baked release ENV를 검산한 뒤에만
normalDockerBuild: true를 기록한다. backend/public/Dagster gateway는 RELEASE_SHA,
admin은 TRANSPORT_ADMIN_RELEASE_SHA를 전체 revision으로 명시한다.
단순 retag는 빌드가 아니며 CLI에 그 기능이 없다. 후보를 최종 머지 이미지로 바꾸어 부르지 않는다.
merge 뒤 실제 merged source/revision으로 정상 빌드를 다시 한다. 같은 입력의 캐시는 재사용한다.

## receipt와 실패

source-manifest.json은 archive/hash·파일별 Git blob/bytes/mode·gitlink를 기록한다.
build-receipt.json의 version1/kind transport-normal-build는 normalDockerBuild,
source/tree/역할별 immutable ID/architecture/COPY/input hash와 redacted log hash를 담는다.
actualApplyAllowed: false, deployReady: false는 항상 유지한다.
관측하지 않은 live schema·instigator·운영 state를 생성하지 않는다.

성공 receipt는 실제 명령과 image identity 검산 뒤에만 배타 생성한다.
실패 시 성공 receipt가 없으며 원 source/log를 보존한다. build 실패, 거부된 source/identity,
환경 오류는 원 command·종료 상태와 함께 QA 증거에서 구분한다.
미실행이나 skip을 성공으로 쓰지 않는다. 원 Docker 출력을 별도 tee하지 않는다.
취소 시 wrapper가 만든 자식 process group만 회수하고 전역 daemon/다른 build는 중지하지 않는다.

기존 M30의 actualMergedNormalBuildCompleted와 소비 측 normalDockerBuild 차이는
원문 hash·원본 필드 전체 동일·실제 완료 flag를 확인한 metadata 호환 copy로만 연결한다.
원본 덮기나 미관측 build의 true 생성은 금지한다. 기존 live-state handoff 검사는 그대로 유지한다.

## 검증과 남은 gate

독립 Python 시험은 real Git archive와 fake Docker를 사용한다. dirty·moved·wrong image/role/
args/OCI/release, ignored secret, 공유 frontend COPY, source 재작성, 출력 redaction,
소유 process group 취소와 원본 receipt 연결을 검사한다. 실제 image나 ABI smoke 결과가 아니다.
추적 지도 E2E는 absolute overlay wrapper와 panel bbox·읽을 수 있는 제목·overflow,
Escape 및 실제 목록 opener focus 복귀를 검사한다. 제품 CSS나 공통 라이브러리는 바꾸지 않는다.

- B1: 선택 Node22.23.1/npm12.0.1 clean Linux install/full gate 및 실제 병합된 Common guard ref 연결 후 publish.
- B2/B3: 승인된 격리 환경의 amd64/arm64 실제 정상 build, source/lock/C11 bytes,
  native worker·ABI·entrypoint 및 필요한 실제 실행 경로 검사. ignore-scripts 자체는 ABI PASS가 아니다.
- B4: 공개·관리자 production runner를 분리하고 USER node와 이미지 내부 cache 소유권을 구현했다.
  전체 node_modules/기존 start 계약을 보존한다. 실제 새 이미지의 uid/config/cache·정상 start·
  로그인fixture·worker·routes·SSR/readiness는 미실행이며 적용 전 필수다.
  backend/CS/gateway UID는 역할별 예외로 유지한다.
  [ADR-017과 실제 probe 계약](../adr/017-web-production-runner-non-root.md)을 따른다.
- B5/B6: 원 두 독립 리뷰, exact CI, 새 추적 E2E 및 기존 공식 Manager 역할별 인계·비선택 보존.
  실제 적용은 기존 런북과 SDK 절차의 별도 권한·증거로만 한다.
- downgrade/DB rollback은 T-DOWNGRADE-GUARDS-20261113 P2 OPEN gate다.
  정상 build/controller는 downgrade를 호출하지 않으며 이 patch에서 DDL을 고치거나 시험하지 않는다.

CI 순서·needs·fail-fast 분석과 재배치는 이 범위에 포함하지 않는다.


## 새 웹 이미지의 production probe

새 실제 이미지가 나온 뒤 기본 USER로 아래 두 역할을 각각 검사한다.
이 문서의 명령은 준비된 검사 절차이며 현재 실제 image 실행 증거가 아니다.

```text
docker run --rm --network none --entrypoint node <공개immutable-imageID> /app/verify-web-runtime.cjs frontend <전체mergedSHA>
docker run --rm --network none --entrypoint node <관리자immutable-imageID> /app/verify-web-runtime.cjs transport-admin-web <전체mergedSHA>
```

검사는 image 자체의 /app과 /home/node cache에서만 실행한다. host bind·임의 --user·키 값은 주지 않는다.
기본 node의 파일 읽기/캐시 쓰기·Next config/native loader·worker 파일 동일성 범위이며
서버 시작·HTTP/로그인·worker 실행/browser의 별도 실제 수용을 대체하지 않는다.
probe 단위 fixture는 make frontend-check/CI에서 실제 temp 파일과 negative permission control로 검사한다.
