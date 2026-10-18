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

- NVMe staging 및 승인된 symlink checkout의 효과 검증, 현재 단일 Compose project와
  관리자 배포 절차를 대조한다. 이번 초기 포트 수정만으로 공식 배포 전체가 수용된 것은 아니다.
- 5개 역할 모두 현재 Memory/MemorySwap0(무제한)이다. 메모리 정책은 별도 작은 변경으로
  구현한다. 현재 웹2개와 gateway의 부팅 이후 peak 합은 기존0.3GiB 예산을 넘는다.
- 공유 서비스의 유한 상한 합만8.375GiB로 물리 약7.5GiB를 넘는다. 개별 한도는 예약 메모리가
  아니지만 모든 서비스 동시 peak를 보장하지 못한다. 실제 Opinet과 동시 수집 조건 수용은 남는다.
- ADR014 accepted·legacy6개 은퇴·실제 Map export/다른 Track 조건은 증거를 대조한 뒤 정산한다.
- daemon OFF, HAProxy 직접 접속 금지 유지. 원본 dirty checkout은 수정하지 않았다.

전체 WSL/Docker 회귀·두 독립 리뷰·이번 후보의 최종 live UI 수용은 아직 후속이다.
