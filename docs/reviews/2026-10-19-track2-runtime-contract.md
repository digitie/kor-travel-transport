# Transport Track 2 현재 운영 계약 정렬

기준 main f9e90bc(PR #89)는 이미 배포·UI34 수용을 마쳤다. 이를 재작업하지 않는다.
Manager main397a91c의 config/docker-targets.yml은 transport host odroid,
consumer_origin http://{host}:12301 및 실제 backend12302/frontend12303/admin12305/code-server12306을 기록한다.

## 재현과 수정

2026-10-19 읽기 전용 조회에서 backend12302/health는 HTTP200/sourcea0b,
14001은 connection refused였다. 배포 스크립트는 PUBLIC_API_PORT14001과
PUBLIC_WEB_PORT14002를 강제하고 gateway와 관리 UI 사전검사도14001을 가리켰다.
신규 계약검사3개 FAIL을 먼저 기록한 뒤 production Compose·env 예시·gateway·
backend/admin 배포 검사 값을 현재12302/12303으로 맞췄다. 관련66개 WSL 검사 PASS다.

## 배포 저장소와 관리자 서비스 범위

사용자의 명시적 Odroid 이전·배포 지시에 따라 이번 운영 수용은 저장소의 과거
과거 Odroid 작업 금지·n150 정본 규칙에 대한 승인된 예외로 수행한다.
현재 정본은 Odroid의 NVMe에 있는 checkout, /opt/kor-travel-odroid/transport.env와
Manager override이며, 기존 정책 파일을 일괄 변경하거나 HAProxy를 수정하지 않는다.
Dagster daemon은 중지 상태를 유지한다.

원격 archive·압축 해제 디렉터리·배포 잠금은 /mnt/media/kor-travel/build/transport를 사용한다.
승인된 checkout과 .env.prod, staging의 실제 장치가 NVMe와 같고 rootfs와 다르며
findmnt SOURCE가 NVMe인지 확인한다. 로컬 archive의 /tmp는 WSL 실행 호스트에만
생성하며 Odroid로 전송한 archive와 압축 해제 파일은 모두 NVMe에 둔다. symlink와 bind mount는 실제 장치 증거로
판단한다. 이 검사는 배포 시에만 수행하며 부팅 조건을 추가하지 않는다.

관리자 배포는 현재 kor-travel-transport project에서 transport-api-gateway와
transport-admin-web만 명시한다. remove-orphans를 제거하여 같은 project의
backend/frontend/code-server를 보존한다. 잘못된 project 재현1 FAIL과 저장소
fixture의 초기 실패 로그를 보존했고 수정 후 집중검사121 PASS를 확인했다.
이 단계 이후의 전체 회귀·실운영 결과는 아래 최종 수용에 기록한다.

## ARM browser 수용

기존 설치 이미지5942696(a0b,arm64)를 network-none/read-only/CPU0.5/메모리1GiB
격리 컨테이너에서 실행했다. Chromium156.0.8078.4가 로컬 HTML title·canvas 픽셀·
PNG 출력을 통과했다. cgroup peak434700288bytes는 로컬 렌더 표본이며 실제 Opinet
수집 peak가 아니다. provider 호출은 하지 않았다. 소유 컨테이너 제거, 외부 runtime
동일, boot 동일, daemon OFF를 확인했다. 실제 API/CS의 OPINET_BROWSER_ENABLED와
TRANSPORT_COLLECTION_ENABLED는 모두 true다. 실패 fallback false를 적용할 사유는 없었다.

첫 r1은 최종 foreign fence 실패로 FAIL이며 before/after 증거가 부족해 원인을 확정하지
않는다. r2는 Mounts 순서 정규화와 증거 보존 뒤 foreign fence는 통과했으나 browser exit1이었다.
fixture가 HOME=/tmp로 바꾼 상태였으며 stderr 저장도 누락됐다. r3에서 이미지의 HOME을
그대로 쓰고 stderr를 보존한 뒤 통과했다. r2의 원인 traceback은 남아 있지 않으므로
HOME 변경을 확정 원인으로 표현하지 않는다. 두 실패를 성공 이력에 합산하지 않는다.

## 남은 조건

- NVMe·단일 project·gateway 정본은 이번 실제 전환에서 수용했다. 이미지 변경이 없는 API/CS/웹은 재빌드하지 않았다.
- 5개 역할 모두 현재 Memory/MemorySwap0(무제한)이다. 메모리 정책은 별도 작은 변경으로
  구현한다. 현재 웹2개와 gateway의 부팅 이후 peak 합은 기존0.3GiB 예산을 넘는다.
- 공유 서비스의 유한 상한 합만8.375GiB로 물리 약7.5GiB를 넘는다. 개별 한도는 예약 메모리가
  아니지만 모든 서비스 동시 peak를 보장하지 못한다. 실제 Opinet과 동시 수집 조건 수용은 남는다.
- 실제 Map 소비자의 export GET은 통과했다. ADR014 accepted·legacy6개 은퇴·다른 Track 조건은 후속 PR에서 정산한다.
- daemon OFF, HAProxy 직접 접속 금지 유지. 원본 dirty checkout은 수정하지 않았다.

아래 최종 수용은 기존 전체 검증의 실패와 수정 후 집중 PASS를 구분한다.

독립 리뷰에서 symlink build 경로의 상속 lock 비교 불일치를 재현했다. 부모가 잠금을
유지할 때 기존 블록 exit2, 양쪽 canonical 경로 비교 뒤 exit0으로 확인했다.
이전 b6301aa 전체 회귀는 수정 전 후보의 INTERRUPTED 이력으로 보존한다.

## 운영 대조에서 확인한 후속 보강

공용 build root는 root 소유이며 배포 계정에 쓰기 권한이 없었다. 상위 권한을 바꾸지 않고
전용 transport staging을 배포 계정 소유0700으로 사전 준비한다. helper는 디렉터리가 없거나
소유자·권한·장치가 다르면 변경하지 않고 거절한다. provision은 별도 검토 후 완료했고 실제 배포 계정의 check-only도 통과했다.

현재 gateway는 저장소 밖의 NVMe bind mount 템플릿을 사용한다. 여기에 존재하던 소비자
전용 /v1/service/exports/ 예외가 저장소에는 없어 공식 관리자 배포가 export를 잃을 수 있었다.
GET-only·기존 upstream·120초 timeout·클라이언트 XFF 제거를 보존하고 단일 IPv4/CIDR
환경변수로 허용 대상을 정본화한다. 빈 값은 deny all이며, 시작 스크립트는 잘못된 주소나
Nginx directive 주입을 파일 쓰기 전에 거절한다. 이번에 IPv6나 다중 소비자 지원은 추가하지 않는다.

실제 Nginx1.27 격리 컨테이너에서 허용GET200, 비허용/빈env403, POST403, 기존공개GET200,
admin/다른service404, XFF제거, injection기동거절을 확인했다. 운영 gateway를 교체한 결과는 아니다.
단순 checkout 갱신은 현재 외부 bind mount를 바꾸지 않는다. 실제 전환에는 현재 허용된 소비자
설정과 mount 정본을 대조하여 gateway에만 적용하고 runtime·UI를 검증해야 한다.

PR #89의 운영 이미지에서 실제 VWorld 성공→VWorld timeout 주입+실제 Kakao fallback→VWorld
복구3건이 통과했다. 주소/도로명/region 존재, runtime불변과 daemon OFF를 확인했다.
DB를 쓰거나 예약수집을 실행하지 않았으며 6개월 자동 갱신 전체 완료를 뜻하지 않는다.

3310c8a 전체 회귀는 WSL1FAIL360PASS1SKIP에서 정상중단했다. 누락된 node health probe의
옛14002 기대값이 원인이며 실제12303 계약으로 맞췄다. Docker도 INTERRUPTED로 보존했다.
이후 staging/export까지 포함한 집중181건 PASS였다. 안정화 뒤 전체 결과는 아래에 보존한다.

## 최종 소스 검증과 기존 금지 조건 정정

7e4e652 전체 검증은 WSL 890 passed / 10 skipped / 1 failed(875.13초),
WSL Docker 890 passed / 10 skipped / 1 failed(964.10초)였다. 두 실패는 모두
test_public_proxies_never_forward_service_exports의 gateway에 service 문자열이
없어야 한다는 기존 조건이다. 실제 운영의 IP 제한 export 경로를 정본화하면서
해당 조건과 충돌했다. 실패 원문을 보존하며 전체 실행을 PASS로 재분류하지 않는다.

2c9553c는 backend/tests/test_service_exports.py만 수정했다. 정확한 export prefix,
소비자 IP include, GET 이외 deny, X-Forwarded-For 제거, 나머지 경로 404,
frontend service 프록시 차단을 검증한다. 제품·배포 스크립트·Compose·gateway 파일은
7e4e652와 동일하다. 관련 service_exports 전체와 gateway 모듈 WSL 검증은
38 passed(307.49초), WSL Docker 검증도 38 passed(333.73초)다.
Docker는 exact source archive·설치 의존성 pin을 검증했고 OOM 없이 종료한 뒤
소유 컨테이너를 제거했다. 새 head CI6개 SUCCESS/live2개 SKIPPED이며 두 backend 전체는
각각899 passed/2 skipped(1548.74초,1220.39초)다. SKIP를 live PASS로 해석하지 않는다.


## 운영 전환과 최종 수용

2c9553c에 대한 독립 두 소스 리뷰는 미해소 P0/P1/P2가 없었다. 정상 staging과
상속 잠금·다른 서비스 보존·allowlist 주입 거부 반례를 포함한다.
r2 prepare는 기존 override의 !override 태그를 safe_load하지 못해 서비스 변경 전에
실패했다. r3는 YAML node의 sequence 값만 바꿔 태그를 보존하고 실제 Compose 반례를
통과했다. 이전 실패는 보존했다. 최종 r4는 새 test-only source/bundle pin만 반영했다.

실제 전환 f036eb68은 정상 stop 뒤 옛 gateway 컨테이너를 보존하고 gateway1개만
교체해 exit0/PASS_OLD_RETAINED로 끝났다. 기존 Nginx image96868d9를 재사용했다.
API/CS/runtime release는 a0b789df, checkout/staged 도구 source는2c9553c다.
canonical env·Manager override와 versioned NVMe gateway 파일을 정렬했고,
다른 역할·daemon OFF·기존 큐를 보호했다. HAProxy 변경은 없다.

n150 Map CS의 실제 설정과 같은 host-network 출발지·기존 키로 export GET1회를
실행해 HTTP200/공항15개,0.685678초를 확인했다. runtime은 불변이고 DB쓰기0이다.
Map의 전체 ETL이나 자동 주기를 대신하는 검증은 아니다.

전환 후 WSL Chromium1243 UI34/34 PASS(0 FAIL/0 NOT_RUN)를 확인했다.
시각은2026-10-18T23:18:18.858Z~23:18:43.998Z이며 다섯 역할의 lifecycle과 daemon OFF가
유지됐다. [공개 배포·소비자·UI 증거](../audits/2026-10-19-transport90-deployment.json)를
따른다. 이 수용 기록을 PR #90에 포함한다. 5role 메모리 정책과 실제 Opinet 전체 수집,
자동 daemon·장시간 수용을 완료로 확대하지 않는다.
