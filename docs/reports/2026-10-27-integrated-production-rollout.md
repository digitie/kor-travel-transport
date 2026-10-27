# 2026-10-27 최종 통합 main 운영 전환

## 현재 체크포인트 — 빌드 진행 중, 운영 수용 미완료

대상은 #141·#138·#143·#139를 합친 main
`d7c36c3c99dafdefe4bc0100fd797662a2b4afd3`다. 검토된 #139 최종 b619와 전체 tree가 같고,
Root의 최종 merge 수용 원장 `transport139-b619-final-merge-root-r1.json`
(`fc9293dae834498e685b1d462fc1fca1a7bebe658d4ade42d026eb9be117a57d`)을 이어받는다.
이 문서는 현재 운영 배포 성공을 선언하지 않는다.

현재 런타임은 `7f01b0133dad73843ce61444830b1020cfd32f0a`다. 별도 소유 unit
`kt-transport-final-d7c36c3c-20261027-final2`가 10월26일23:29:52 UTC에 정본 G를 취득하고,
원본 다섯 역할·이미지·설정·타 서비스 상태를 보존했다. 23:32:25 UTC부터 backend 사전 빌드를
한 번 실행 중이다. 이 체크포인트에는 Transport 일정 중지·서비스 교체·공개 UI 수용이 없다.
기존 [주차 배포·복구 기록](2026-10-26-parking-production-rollout.md)은 원문 그대로 유지한다.

## 소유 범위와 원본 보호

- 빌드·이미지·앱·cache·tmp는 기존 NVMe 경로를 사용한다. 원본 개발 checkout의 dirty와
  다른 작업자의 변경은 복사하거나 되돌리지 않는다.
- Manager G 다음 Transport R의 공식 순서를 유지한다. 사전 빌드 뒤 새 snapshot으로
  Transport instigator만 중지하고, queued/run과 물리 worker의 자연 종료를 확인한다.
- Weather 이미지·컨테이너·instigator·실행 중 job, 공용 PG·Dagster daemon·plane은 변경하지 않는다.
  `prepare-shared-dagster-cutover`와 공용 plane converge도 호출하지 않는다.
- 전용 builder9415의 원래 제한을 유지한다: CPU0.75코어, 메모리1.5GiB,
  memory와 swap 합계3GiB다. shared builder9598는 변경하지 않으며, 완료 뒤9415를 원래 STOPPED로 복원한다.
- 실제9415 부모 cgroup과 컨테이너 내부에서 `cpu.max=75000 100000`,
  `memory.max=1610612736`, `memory.swap.max=1610612736`을 확인했다.
  최초 `docker-init` 하위 `init`의 상속 값을 직접 한도로 오인한 검산 실패는 보존했다.
- 실제 현재 solve가9415 전용 builder에 속함을 확인했다. 선택한 프로세스 역할에서
  pip 하위 g++/cc1plus의 네이티브 컴파일을 확인했지만 구체 패키지와 전체 CPU 기여율은 수용하지 않았다.

## Manager 정본 소비와 복구 경계

정본 CLI show의 네 필드 `host/max_concurrent_runs/path/sha256`를 기존139 validator로 읽는다.
Odroid의 prepared a7은 기존 정책 max5·Geo1·Weather3·external2·slow1·WARNING을 보존한다.
살아 있는 공용 plane의 내부 파일은 여전히 c444이며 prepared a7과 별도로 검증한다.
호스트 alias가 현재 가리키는 파일과 기존 컨테이너의 bind inode를 같은 것으로 판정하지 않는다.

원 controller 초안은 이미지 rollback에서 Manager 경로를 전달하지 않는 P1 반례가 있었다.
실제 이미지 재생성 때는 후보 validator를 stdin으로 사용해 같은 네 필드를 다시 확인하고,
canonical path를 rollback 환경에도 전달하도록 정렬했다. CS는 같은 canonical Source의
read-only bind만 허용한다. 반대로 교체 전 중단은 원 CID·image·started_at·mount 전체가 같은
미교체 런타임을 검산하며, 새 경로에 맞추려고 컨테이너를 재생성하지 않는다.

재검증 parent 기한은 기존120초에 맞췄다. 제품 안쪽 hostname15초·registry60초·show30초는
변경하지 않았다. 원 P1과 원 실행 전 검산 실패는 지우지 않았다.

## 검증 원장과 남은 수용

- controller `f2c57159da8d03692efc9bda210aa64732c9aad4c50c194fc29db60fabb324ec`,
  helper `e4600b254981b3303d873139b5fc3fd34717851a0991a15335e746d93006b6e3`,
  archive `056b29e25e5a7f7d3cfd8d34e3a765311265366f33b6d1129b30064f8e37c226`으로 결박했다.
- 변경한 controller 경계는 Linux 순수26개0.133초와 Root/J의 독립 검토로 확인했다.
  Root `b4a2b08c9e1b98c8f9a76a8dc8bc405499169f27551974389f9671ca51f8c720`,
  J `3d7bf4558e76ed1fefaa8e4ce0cce2f5f236c86f2f9fea79e465b56878fce8a3`다.
  원 운영 controller의 역사적58개를 이번에 재실행한 것으로 세지 않는다.
- 사전 읽기 검산 `transport-final-d7c36-before-readonly-t-r1.json`
  (`17f1a796774c529f7761ebe58a4bac38d31bf830e33c6a159a3d2e605a4e8019`)에
  fixed Weather/plane container와 실제 plane 내부 c444·현재 active run을 남겼다.
- 실제 cgroup 수용은 `transport-final-d7c36-bounded-builder-actual-caps-t-r3.json`
  (`bf5aed904f11b919618bf810aca67d2ed32a9ef00027ac6e0a893c17a16a0aa8`)이다.
- 남은 수용은 세 사전 빌드 종료, fresh Transport-only pause/drain/state 보존, 공식 교체,
  API/admin fullSHA·다섯 역할 healthy·schema0035, 실제 CS canonical Source/RWfalse/insideSHA,
  Weather/공용 plane 보존, 원래 instigator 상태와 builder STOPPED 복원, 공개 TLS UI32다.

전체 수집의 CPU/RSS 감소, idle CPU·cadence·routine health 개선, 공용 plane 전체 a7 수렴은
이번 배포 완료와 같지 않다. 기존 [국소 scalar 계량](2026-10-26-plain-json-scalar-cpu.md),
[로그인 소비자](2026-10-26-login-hydration-common-adoption.md),
[Manager caller 범위](2026-10-26-manager-host-instance-caller.md)의 원 실패와 미검증 한계를 보존한다.
