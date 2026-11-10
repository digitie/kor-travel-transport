# 기준정보 최초 본문 구성 개선

## 문제와 변경

동일 데이터라도 cursor의15분 epoch가 오래 지나면 전체 본문을 다시 조립·저장했다.
[실제 원인 분석](2026-11-10-reference-cold-build-analysis.md)의 ARM64 격리 측정은 최초9.651/9.908초,
그중 구성8.746/8.950초였다. 이번 변경은 cursor 수명을 늘리지 않고 본문과 handle을 분리한다.

- 입력 revision별 불변 artifact/items를 저장하고 현재 head와 모든 잔존 handle의 FK로 보호한다.
- 같은 입력이면 장기 유휴 뒤에도 작은 handle만 발급한다. 입력 실제값 해시는 계속 계산하며 상태 TTL은 추가하지 않는다.
- canonical JSON 배열을 한 bind의 `INSERT SELECT`로 저장해 행별 재파싱/재직렬화를 줄인다.
- 주소 JSON은 기존 소비 필드3개만 투영한다. 기존 DTO와 좌표·공급자·시각 검증은 유지한다.
- 기존 수집/주소 갱신 뒤 준비를 연결하고, 예약 없는 내부 `reference_export_prepare_job`을 추가한다.
  source head나 공급자 자료를 새로 수집하는 job은 아니다. 원20 instigator 목록은 바꾸지 않는다.
- migration0042는 가산 변경이다. 기존 NULL FK snapshot/항목은 그대로 읽고, 기존 cursor 만료도 유지한다.

[ADR-016](../adr/016-reference-export-artifact-lifetime.md)에 수명·동시성·GC 경계를 기록했다.

## 검증

WSL PG18에서 migration/모델 정합성과 lifecycle·구 cursor·동시 첫 조회·GC를 확인했다.
첫 동시 조회 시험은 시각을 고정하지 않아 handle 동일성에서 실패했고, 시각을 고정한 시험은
동일 handle·본문1개 저장을 확인했다. 기존 실패 로그를 보존하며 epoch 경계가 원인이라고 단정하지 않는다.
새 Dagster 시험의 잘못된 의존성 조회 API는 시험 코드만 정정했고 관련3개가 통과했다.
Docker PG18의 같은 집중 묶음은 **41통과·경고3개**다. 겹치는 시험을 합산하지 않는다.
Ruff의 문법·미정의·미사용 import 검사와 diff 검사가 통과했다.

검증 원장은 Git 밖 `transport-artifact-lifecycle-20261110` 아래의 각 QA 로그다.
운영은 아직 제품d0c9010/schema0041이다. 다음은 최소 API/수집기 빌드, 같은 ARM64 fixture의
미준비/유휴/사전 준비 비교, 원 수집 자연 종료 뒤0042 적용과 실제 서비스 수용이다.

## 남는 한계

입력 해시는 실제 원천·주소·매핑 값을 읽으므로 비용이 남는다. 아직 준비되지 않은 새 revision은
요청에서 기존 상한 안에 구성하는 fallback이 있다. 준비 작업의 시간을 HTTP 시간에서 숨겨
전체 처리량 개선으로 주장하지 않으며, 격리 단일 표본을 운영 p95로 해석하지 않는다.
