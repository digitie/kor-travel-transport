# ADR-016: 기준정보의 불변 본문과 HTTP cursor handle 수명을 분리한다

- **상태**: accepted (제품7a5d0c4·운영0042 수용)
- **날짜**: 2026-11-10
- **결정자**: agent + human
- **컨텍스트**: 사용자가 최초 본문12.43초의 분석 뒤 개선을 승인했다. 분석에서 요청 중 전체 조립·저장과
  15~30분 cursor 만료 뒤 같은 본문까지 재생성되는 경로를 확인했다. 데이터 신선도·실패 즉시 반영과
  기존 cursor의 고정 집합/만료 계약은 유지해야 한다.
- **결정**: `reference_export_artifacts/items`에 입력 revision별 불변 본문을 저장하고,
  `reference_export_artifact_heads`가 종류/설정 범위별 현재 본문을 pin한다. `service_export_snapshots.artifact_id`
  FK로 작은 유한 handle을 발급한다. 기존 NULL FK의 handle/항목은 그대로 읽는다. 데이터 revision에는
  실제 source·주소·매핑·release 값을 사용하며 상태 TTL은 늘리지 않는다.
- **근거**: cursor TTL만 늘리면 데이터 본문과 탐색 수명의 결합이 남는다. 매 epoch마다 항목 복사도
  피하려면 불변 본문과 handle을 별도 식별해야 한다. 현재 head와 남아 있는 모든 handle이 참조한 본문은
  삭제하지 않으며, key-share/skip-locked와 FK가 재사용/GC 경합을 보호한다. head는 새 revision에만 바꾼다.
- **결과 (긍정)**: 장기 유휴 뒤에도 같은 본문을 다시 구성하지 않고 새 handle만 발급한다. 기존 수집 후
  준비 op와 예약 없는 내부 준비 job이 HTTP 밖에서 canonical 본문을 생성할 수 있다. JSON 배열의
  `INSERT SELECT`로 재파싱·행별 JSON serializer 반복도 줄인다.
- **결과 (부정)**: migration0042와 파생 본문 보관/GC 관계가 추가된다. 범위는 서버 설정으로 정해지며
  질의별 캐시를 생성하지 않는다. 현재 본문과 남아 있는 handle의 pin은 유지한다. 입력 해시의 전체 값
  확인 비용은 여전히 남고, 아직 준비되지 않은 새 입력은 기존처럼 요청에서 안전하게 구성한다.
- **검증**: 유휴/구 cursor·실패 상태·동시 생성/GC·migration과 Docker PG18 집중41개,
  ARM64 교대 비교·운영 새 이미지/0042·내부 준비/실제 HTTP를 수용했다.
  [수치·실패 이력·남는 비용](../reports/2026-11-10-reference-artifact-improvement.md)을 구분한다.
- **후속**: 전체 CI backend 결과를 정산한다. 조건부304·입력 해시·미준비 구성 비용은 남는다.
  모든 writer를 포괄하는 revision을 입증하기 전에는 입력 해시를 단순 timestamp로 대체하지 않는다.
