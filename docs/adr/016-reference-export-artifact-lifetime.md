# ADR-016: 기준정보의 불변 본문과 HTTP cursor handle 수명을 분리한다

- **상태**: accepted
- **날짜**: 2026-11-10 / 2026-11-25 (결정 갱신 — 입력 revision namespace를 본문 코드 지문으로)
- **결정자**: agent + human
- **컨텍스트**: 사용자가 최초 본문12.43초의 분석 뒤 개선을 승인했다. 분석에서 요청 중 전체 조립·저장과
  15~30분 cursor 만료 뒤 같은 본문까지 재생성되는 경로를 확인했다. 데이터 신선도·실패 즉시 반영과
  기존 cursor의 고정 집합/만료 계약은 유지해야 한다.
- **결정**: `reference_export_artifacts/items`에 입력 revision별 불변 본문을 저장하고,
  `reference_export_artifact_heads`가 종류/설정 범위별 현재 본문을 pin한다. `service_export_snapshots.artifact_id`
  FK로 작은 유한 handle을 발급한다. 기존 NULL FK의 handle/항목은 그대로 읽는다. 입력 revision에는 실제
  source·주소·매핑 값과 **본문 코드 지문**(`export_references.REFERENCE_PAYLOAD_FINGERPRINT` — 본문을 바꿀 수 있는 코드·
  page schema·의존성 버전만 해시)을 사용하며 상태 TTL은 늘리지 않는다. 지문을 만들 수 없으면 artifact 없이 완전
  구성 경로로 간다(정확하지만 느리다). 배포 직후 준비는 API와 같은 지문의 code-server에서만 한다.
  _(2026-11-25에 배포 식별자 `RELEASE_SHA`를 본문 코드 지문으로 바꿨다 — 아래 [결정 갱신](#결정-갱신-2026-11-25).)_
  → 세부: [기준정보 본문 코드 지문](../architecture/performance.md#기준정보-본문-코드-지문2026-11-25)(해시 입력·범위 가드·
  ETag·저하 표시·이전), [오프라인 준비의 격리·상한·정리](../architecture/performance.md#기준정보-본문-오프라인-준비의-격리상한정리2026-11-24)
  (예산·busy·GC 값), [배포 런북](../runbooks/deployment.md#배포-직후-best-effort-warm기준정보-본문-준비loopback-export-확인-2026-11-24)
  (배포 직후 준비 절차·exit code)
- **근거**: cursor TTL만 늘리면 데이터 본문과 탐색 수명의 결합이 남는다. 매 epoch마다 항목 복사도
  피하려면 불변 본문과 handle을 별도 식별해야 한다. 현재 head와 남아 있는 모든 handle이 참조한 본문은
  삭제하지 않으며, key-share/skip-locked와 FK가 재사용/GC 경합을 보호한다. head는 새 revision에만 바꾼다.
  배포 식별자 대신 코드 지문을 쓰는 이유: 배포마다(같은 코드 재배포·문서만 바뀐 배포 포함) 모든 본문이 무효가 되고,
  API와 code-server의 `RELEASE_SHA`가 다르면 서로 head를 뒤집었기 때문이다. 덜 무효화되어 낡은 본문을 내는 것보다
  더 무효화되는 편이 싸므로 함수가 아닌 모듈 단위로 해시하고, 지문 밖 코드가 builder에서 닿으면 시험이 실패한다.
- **결과 (긍정)**: 장기 유휴 뒤에도 같은 본문을 다시 구성하지 않고 새 handle만 발급한다. 기존 수집 후
  준비 op와 예약 없는 내부 준비 job이 HTTP 밖에서 canonical 본문을 생성할 수 있다. JSON 배열의
  `INSERT SELECT`로 재파싱·행별 JSON serializer 반복도 줄인다. 지문 입력이 그대로인 배포는 artifact를 재사용하고,
  `RELEASE_SHA` 없이 띄운 컨테이너도 artifact 경로를 쓴다.
- **결과 (부정)**: migration0042와 파생 본문 보관/GC 관계가 추가된다. 범위는 서버 설정으로 정해지며
  질의별 캐시를 생성하지 않는다. 현재 본문과 남아 있는 handle의 pin은 유지한다. 입력 해시의 전체 값
  확인 비용은 여전히 남고, 아직 준비되지 않은 새 입력은 기존처럼 요청에서 안전하게 구성한다. 지문 구성 방식이
  바뀐 첫 배포에서는 모든 본문을 한 번 다시 만든다.
- **검증**: 제품 `7a5d0c4`·운영 DB 0042에서 수용했다. 유휴/구 cursor·실패 상태·동시 생성/GC·migration과 Docker PG18
  집중41개, ARM64 교대 비교·운영 새 이미지/0042·내부 준비/실제 HTTP를 수용했다.
  [수치·실패 이력·남는 비용](../reports/2026-11-10-reference-artifact-improvement.md)을 구분한다.
- **후속**: 조건부304·입력 해시·미준비 구성 비용은 남는다. 모든 writer를 포괄하는 revision을 입증하기 전에는
  입력 해시를 단순 timestamp로 대체하지 않는다.

### 사실 갱신(2026-11-24, 결정 불변)

준비 경로의 종류별 격리·예산 하나·busy 이월·제한 정리·HTTP 정리의 savepoint 격리를 보강했다. 결정은 그대로다.
→ 세부: [오프라인 준비의 격리·상한·정리](../architecture/performance.md#기준정보-본문-오프라인-준비의-격리상한정리2026-11-24)

<a id="결정-갱신-2026-11-25"></a>
### 결정 갱신(2026-11-25)

입력 revision namespace의 배포 식별자를 `release_sha`에서 본문 코드 지문으로 바꿨다(위 "결정"에 접었다). 배포 직후
준비의 `RELEASE_SHA` 대조도 지문 대조로 바꿨다. 지문 입력이 그대로인 배포는 artifact를 재사용하고, 처음 배포될 때만
모든 본문을 한 번 다시 만든다.
→ 세부: [기준정보 본문 코드 지문](../architecture/performance.md#기준정보-본문-코드-지문2026-11-25)
