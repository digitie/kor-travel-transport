# Manager 정본 문서 대조

Manager main397a91ca0df6a53a328127065b41e940dd23eaf0의 decisions.md,
prod-deployment.md, docker-management.md를2026-10-19에 읽었다. 원격 운영 호출은 없다.

prod-deployment §9.2의 현재②는 workspace digest 갱신·같은 SHA 설치·targets validate
뒤 dagster-plane converge --dry-run/--confirm으로 plane을 먼저 갱신하고 Transport를
배포한다. 운영 호스트에서 공용 PG를 포함한 ensure dagster는 거부한다.
Transport ADR-014의 옛 'ensure dagster 먼저' 문구는 plane/workspace 선행이라는
의도로 해석하되 실제 명령은 이 converge 절차를 따른다. 기존 plane에 다시 ensure를
실행해 예전 수용 순서를 재현하지 않는다.

§9.2④는 소비자 검증 뒤 HAProxy 전환이라는 일반 순서다. Transport의 기존 pr/pr-api
host 선전환 예외는 ADR-014 결정8과 실제 사용자 설정 이력으로 구분한다.
현재 HAProxy는 사용자가 관리하며 이 문서 작업에서 접속·변경하지 않는다.

같은 §9.2②의 'deploy-prod.sh가 아직 없다' 문장은 과거 계획 설명이다.
PR84·PR90의 실제 구현과 현재 공식 entry가 우선한다. Manager 문서를 수정하는
별도 작업으로 확대하지 않고 이 불일치를 기록한다.

이 문서 대조와 PR90 소비자GET·gateway/UI, 기존 ARM·Manager 설치 증거 및 현재 양 호스트 run0/location 검사를 연결해 ADR-014의 현재 운영 결정을 수용했다. 최초 전환의 load-error 순간 원문은 미회수로 분리한다. 5role 메모리 및 실제Opinet run 수용은 별도다.

읽은 문서 SHA256:
- decisions.md: 8c13aaf5946d1aae7aea522406364cdbacde49aa41fa66f97a22e373320799bf
- prod-deployment.md: ab598d65f8e4320d0cf739f8ebe7baad3be20269fe0ebb4bf19033c667984891
- docker-management.md: c95f662ca54e7616b6f40d10bc2e161c30d9b6a0b08e581efc39fe9e3a5666c7
