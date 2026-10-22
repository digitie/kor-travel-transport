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
   실패하면 실제5역할 한도와4파일 상태를 기록하고 자동 재시도·복구를 하지 않는다.
   Docker29의 update0은 변경없음이고-1은 거절되므로 무제한 복구에는 별도 승인한 공식
   Compose recreate가 필요하다. 기존 PID 유지와 무제한 복구를 동시에 보장하지 않는다.
4. 주소 cycle 뒤 실제 CS에서 DefaultRunLauncher로 fuel job을 한 번 실행한다.
   due 예약 강제 변경·자동 재실행 없이 기존 multiprocess를 유지한다.
5. 실제 CS 전체 peak/CPU·OOM·native 종료·DB lineage와 UI를 검증한다.

현재 상태: 후보 구현. cap 적용·실제 fuel·배포 후 UI 미실행.
기존 oneoff 하니스는 미실행 보존하며 실패 원문도 삭제하지 않는다.

## 로컬·CI 검증

제품6d095ed의 CI6개 SUCCESS / live2개 SKIP. backend 두 실행은 각각906 PASS/2 SKIP다.
현재후보의 WSL 계약7 PASS, Docker 격리계약7 PASS와 실제 Compose 렌더 비교를 통과했다.
5역할 memory/swap byte값이 같으며 두 모델의 그 외 필드는 이전 정본과 동일했다.
운영 변경 도구는 부분파일 교체 실패·실제cap 잔류 기록 반례를 포함해6 PASS다.

로컬검증기 최초에는 Compose byte값의 문자열형 처리와 read-only 중첩 mountpoint
준비 누락으로 실패했다. 제품 실행 전의 검증환경 오류였고, 수정한 r3에서7 PASS했다.
Docker29.1.3 별도격리 실험은0/0 복구가 no-op이고-1/-1은HTTP400임을 확인했다.
따라서 자동rollback 성공을 주장하는 기존 준비안은 철회하고 부분상태 보존으로 수정했다.

운영 적용·최종cap하 실제 Opinet·배포 후 UI는 아직 미실행이다. 이 문서 수정의
skip-ci는 제품6d095ed 검증을 대체하지 않는다.
