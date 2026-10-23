# 2026-10-23 유가 동시성 개선 배포·검증 기록

상태: **배포 진행 중**. 코드 머지·회귀 검증·공식 NVMe stage는 완료했으며 아래 운영 전환과 실제 수집은 아직 NOT_RUN이다.

## 코드와 검증

- 최종 제품 PR #106: 검증 HEAD `97abbc9caf06f18574f154813d75ce8cbb64b4c3`, merge `af415b3207383b08c560128879168e2663629596`. 두 Git tree가 같음을 확인했다.
- 통합 범위: #103 수집 상한 12,600초·진행 로그·export 유예, #104 원본 저장과 통계 세대 준비/짧은 공개 잠금 분리, #105 시작 기준 다음 예약, #106 대체 scheduler 진입·대기 시각 정합.
- 최종 WSL PostgreSQL: 980 PASS / 2 SKIP, 1,903.09초. 최종 Docker: 977 PASS / 5 SKIP, 1,739.17초. Docker의 추가 3 SKIP은 내부 Docker CLI가 없는 배포 계약 검사이며 CI에서는 실행했다.
- 두 CI 실행 모두 backend·frontend·admin SUCCESS. backend 980 PASS / 2 SKIP. workflow live-e2e는 SKIPPED이며 별도의 공개 HTTPS UI 검증과 구분한다.
- James·Popper가 최종 제품 HEAD를 각각 PASS했다. 원본 commit 후 파생 실패가 source 성공을 취소하던 경계, cleanup rollback 뒤 만료된 ORM 접근, 실패/claim 예약에 성공 여유를 더하던 경계를 수정했다.
- 직전 코드의 Docker 첫 전체 실행은 설치 소스 `/app`와 테스트 bind `/workspace`가 달라 오류 프레임 검증 2건 실패했다. `PYTHONPATH`를 bind 소스로 고정한 뒤 전체가 통과했다. 제품 실패를 숨기거나 테스트 단언을 완화한 결과가 아니다.
- frontend 130개, admin 225개와 build/type-check가 통과했다. 최종 제품에서 해당 UI 소스는 변경하지 않았다.

## 성능의 증거와 한계

전용 PostgreSQL 합성 12,000곳·60,000가격의 두 번 비교에서 공개 잠금은 기존 16.069/13.684초에서 새 0.163/0.140초로 줄었다. 전체 집계는 기존 16.073/13.686초, 새 16.121/14.395초였다. Python 추적 최대는 냉 실행 4.722→2.773 MiB, 온 실행 2.755→2.686 MiB였다. 개발 환경의 잠금 개선이며 전체 수집 CPU·시간·Odroid worker RSS 감소를 입증하지 않는다.

배포 전 16초 표본은 host CPU 100%였다. 이전 릴리스의 실제 수집과 제한된 ARM 빌드가 겹친 측정이므로 배포 전후 성능 비교에 사용하지 않는다. ARM 빌드는 한 코어 75%, 1,536 MiB 상한이며 소스·이미지·캐시는 NVMe를 사용한다. 옛 후보 `3b9b16e` 빌드는 #105/#106 통합 뒤 대체돼 취소했으며 배포하지 않았다.

## 공용 PostgreSQL pause 관측

배포와 instigator 중지를 시작하기 전에 공용 PostgreSQL이 `paused`인 것을 확인했다. 가벼운 Dagster HTTP는 응답했지만 실행 목록 쿼리는 40초를 넘겼고 API/daemon은 unhealthy가 됐다. pause를 건 주체·시작 원인은 미확인이다.

00:46 UTC에 Manager global mutation lock을 확보하고 동일 PG container ID의 pause만 해제했다. 재시작·재생성·schema 변경은 없었다. 이후 PG·API·daemon healthy와 Dagster 실행 목록 조회가 복구됐다. 이를 제품 배포 실패나 CPU 개선 효과로 집계하지 않는다.

## 운영 수용 게이트

- 공식 `DEPLOY_STAGE_ONLY=true`, Manager target·NVMe·tracked override 검증: PASS. 최종 merge 소스만 stage했고 runtime은 아직 교체하지 않았다.
- 배포 전 API/CS: `rel-86398267fc32`, schema `0028_fuel_statistics`.
- ARM 이미지 완료 및 공식 배포: NOT_RUN.
- schema `0029_fuel_statistics_generations`, API/CS 이미지·release SHA, frontend HTTP, gRPC 12306·정상 location: NOT_RUN.
- 공용 PG·daemon·Weather·Geo container 보존, Transport instigator 원래 상태 복원: NOT_RUN.
- 실제 `rest_area_fuel_price_collection_job`의 Dagster SUCCESS·원본 CollectionRun·공개 세대 연결: NOT_RUN.
- 배포 후 공개 HTTPS UI 14개: NOT_RUN. 배포 전에는 14 PASS, JS/HTTP 오류 0, 실제 VWorld 요청 51 성공/0 실패를 확인했다.

배포 controller와 실제 수집 검증 스크립트도 두 독립 리뷰를 거쳤다. DB/외부 명령에 상한을 두고, 배포 timeout의 하위 작업 종료가 불명확하면 `OPERATION_TIMEOUT_UNKNOWN`으로 pause를 유지한다. 종료를 증명하지 못한 정방향 작업과 자동 rollback을 겹치지 않는다. 실제 수집 관찰 시간 초과가 worker를 강제로 죽였다는 뜻도 아니다.

운영 비밀 env·로그는 커밋하지 않는다. 배포와 실제 수집의 root 전용 증거는 NVMe release 디렉터리에 보관하고 이 문서에는 검증 결과만 정산한다.
