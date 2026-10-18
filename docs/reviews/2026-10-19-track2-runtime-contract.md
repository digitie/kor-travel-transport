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

원격 archive·압축 해제 디렉터리·배포 잠금은 /mnt/media/kor-travel/build를 사용한다.
승인된 checkout과 .env.prod, staging의 실제 장치가 NVMe와 같고 rootfs와 다르며
findmnt SOURCE가 NVMe인지 확인한다. 로컬 archive의 /tmp는 WSL 실행 호스트에만
생성하며 Odroid로 전송한 archive와 압축 해제 파일은 모두 NVMe에 둔다. symlink와 bind mount는 실제 장치 증거로
판단한다. 이 검사는 배포 시에만 수행하며 부팅 조건을 추가하지 않는다.

관리자 배포는 현재 kor-travel-transport project에서 transport-api-gateway와
transport-admin-web만 명시한다. remove-orphans를 제거하여 같은 project의
backend/frontend/code-server를 보존한다. 잘못된 project 재현1 FAIL과 저장소
fixture의 초기 실패 로그를 보존했고 수정 후 집중검사121 PASS를 확인했다.
전체 회귀·실운영 배포 검증은 아직 남아 있다.

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

- NVMe·단일 project 수정은 로컬 구현까지 완료했다. 공식 배포 전체의 운영 수용은 후속 검증이다.
- 5개 역할 모두 현재 Memory/MemorySwap0(무제한)이다. 메모리 정책은 별도 작은 변경으로
  구현한다. 현재 웹2개와 gateway의 부팅 이후 peak 합은 기존0.3GiB 예산을 넘는다.
- 공유 서비스의 유한 상한 합만8.375GiB로 물리 약7.5GiB를 넘는다. 개별 한도는 예약 메모리가
  아니지만 모든 서비스 동시 peak를 보장하지 못한다. 실제 Opinet과 동시 수집 조건 수용은 남는다.
- ADR014 accepted·legacy6개 은퇴·실제 Map export/다른 Track 조건은 증거를 대조한 뒤 정산한다.
- daemon OFF, HAProxy 직접 접속 금지 유지. 원본 dirty checkout은 수정하지 않았다.

전체 WSL/Docker 회귀·두 독립 리뷰·이번 후보의 최종 live UI 수용은 아직 후속이다.

독립 리뷰에서 symlink build 경로의 상속 lock 비교 불일치를 재현했다. 부모가 잠금을
유지할 때 기존 블록 exit2, 양쪽 canonical 경로 비교 뒤 exit0으로 확인했다.
이전 b6301aa 전체 회귀는 수정 전 후보의 INTERRUPTED 이력으로 보존한다.
