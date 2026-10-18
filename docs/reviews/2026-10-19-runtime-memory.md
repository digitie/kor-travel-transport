# 운영 메모리 한도와 실제 유가 수집 수용

후보는 API512 / CS2560 / 공개 웹384 / admin512 / gateway64MiB, 합계4032MiB다.
memswap_limit은 mem_limit과 같아 추가 swap을 허용하지 않는다.
제품·이미지·provider 설정은 변경하지 않는다.

읽기 전용 cgroup 관측 peak는 각각157.6 / 358.5 / 154.1 / 169.3 / 8.36MiB다.
CS는 승인된 worker 예산2048MiB와 상주 peak358.5MiB에153.5MiB 여유를 둔다.
다른 역할도 관측의 여유를 둔 초기값이다. 최적값이나 전체 Opinet 실측값이 아니다.
T-TRN-05는 실제 수집 수용 전까지 미완료다.

호스트 모든 서비스의 최대 한도를 동시에 쓸 수 있다는 보장은 없다. daemon OFF와
수집 하나만 실행하며 적용 직전 current가 후보보다 작은지 확인한다. MemAvailable이
역할별 max(후보-current,0) 합계와1GiB 예비량보다 커야 한다. 공용 PG는 변경하지 않는다.

## 수용 순서

1. WSL/Docker 계약 검증, CI, 독립 적대 리뷰2개를 통과한다.
2. Compose 및 Manager canonical override2개에 같은 한도를 영속화한다.
3. lock·PID·설정·queue·daemon OFF를 확인하고 Docker update로 memory/swap만 바꾼다.
   실패하면 현재 상태부터 확인하고 원래0 한도로 복구한다.
4. 주소 cycle 뒤 실제 CS에서 DefaultRunLauncher로 fuel job을 한 번 실행한다.
   due 예약 강제 변경·자동 재실행 없이 기존 multiprocess를 유지한다.
5. 실제 CS 전체 peak/CPU·OOM·native 종료·DB lineage와 UI를 검증한다.

현재 상태: 후보 구현. cap 적용·실제 fuel·배포 후 UI 미실행.
기존 oneoff 하니스는 미실행 보존하며 실패 원문도 삭제하지 않는다.
