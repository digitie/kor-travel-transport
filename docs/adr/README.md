# ADR — 결정 기록

ADR은 "나중에 코드를 본 사람이 **왜 이런 구조인지**(맥락과 트레이드오프)를 이해하게 하는" 기록이다.
주로 되돌리려면 큰 리팩터링·데이터 이전이 필요하거나 여러 모듈·저장소를 제약하는 결정을 남긴다. 값·임계치·필드·절차처럼 코드 리뷰나
리팩터링 수준에서 바뀌는 것은 ADR에 적지 않고 더 맞는 문서에 둔다 — 세부가 ADR에 쌓이면 코드가 바뀔
때마다 ADR이 어긋나고(문서 부패), 결국 ADR 전체를 믿지 않게 된다.

## ADR을 쓸지 판단하는 체크리스트

셋 중 **하나라도** 해당하면 ADR을 쓴다.

1. **비용** — 6개월 뒤 이 결정을 뒤집으려면 며칠 이상(마이그레이션·다른 저장소 동시 변경·운영 이전)이 드는가?
2. **영향 범위** — 여러 모듈·서비스·저장소(Map·Manager·Common 등)나 다른 작업자의 방식에 제약을 거는가?
3. **대안과 대가** — 뚜렷한 대안(A vs B)이 있었고, 알려진 단점을 감수하고 이쪽을 골랐는가?

3번만 해당하고 되돌리기 쉬운 선택이면 ADR 대신 설계 문서나 PR 본문에 대안 비교를 남긴다.

큰 기능은 전체 흐름·세부 스펙을 `docs/design/` 설계 문서에 쓰고, 그중 핵심 분기점 1~2개만 ADR로 뗀다.

## 담는 것 / 담지 않는 것

| ADR에 담는다 (아키텍처) | ADR에 담지 않는다 (구현 세부) → 둘 곳 |
|---|---|
| DB·저장 방식 선택, 데이터 수명 원칙 | 컬럼 타입·인덱스·쿼리 튜닝, DB 설정값 → `docs/architecture/data-model.md`·`performance.md` |
| 외부 계약의 형태와 원칙(버저닝, 인증 방식, "현재 집합을 증명 못 하면 503") | 엔드포인트 필드·에러 code 사전·`Retry-After` 값·timeout 초 → `docs/openapi.json`, `docs/map-service-*.md`, `docs/architecture/*` |
| 인증·네트워크 경계, 운영 호스트·배포 모델 | 배포 명령 순서·체크리스트·`file:line` → `docs/runbooks/*`, 검증 증거 → `docs/audits/`·`docs/reports/` |
| 수집 구조(예약·트랜잭션 분리), provider 라이브러리 경계 | 수집 주기·시간 상한·재시도 횟수 → `docs/architecture/collection.md` |
| 핵심 프레임워크·라이브러리·런타임 모델 도입 | 이미지 경로별 권한 표·Dockerfile 세부 → Dockerfile 주석·런북 |
| — | 작업 절차·에이전트 규칙 → `AGENTS.md`·`SKILL.md`·`docs/runbooks/*` |
| — | 작은 변경의 이유 → 커밋·PR 본문·`docs/journal.md`, 진행 상황 → `docs/tasks.md` |

## 개정 규칙

- ADR 본문은 **결정이 바뀔 때만** 고친다. 값·임계치 조정, 구현 진행, 운영 사실 확인은 위 표의 문서만
  고치고 ADR에서는 그 문서를 링크한다. "사실 갱신"·"개정" 절을 ADR 끝에 계속 덧붙이지 않는다.
- 결정을 고칠 때 번호(예: "결정 3")는 **새 의미가 옛 의미를 포함할 때만**(범위를 넓히거나 조건을 더할 때) 유지한다.
  뜻이 달라지면 새 번호를 붙이고 옛 번호 옆에 "→ 결정 N으로 바뀜"을 남긴다. 기존 인용("ADR-013 결정 3")의 뜻이
  조용히 바뀌지 않게 하기 위해서다. 원칙 자체가 뒤집히면 새 ADR을 쓴다.
- 대체 관계:
  - **전체 대체** — 옛 ADR 상태를 `superseded by ADR-XXX`로 바꾼다. 원 본문은 지우지 않는다.
  - **일부 대체·범위 축소** — 옛 ADR은 `accepted`를 유지하고 상태 줄에 "(결정 N은 ADR-XXX가 대체)" 또는
    "(…범위는 ADR-XXX가 좁힘)"을 적고, 해당 결정 옆에도 링크를 단다. 새 ADR은 `대체`/`보완` 필드로 옛 ADR을 가리킨다.
- 상태 줄은 `proposed | accepted | superseded by ADR-XXX` 중 하나와, 필요하면 괄호 하나만 붙인다:
  위 대체 관계, 또는 진행 위치 포인터 "(→ 진행: `docs/tasks.md` <ID>)". "구현 완료"·"QA 미완" 같은 진행 서술은 쓰지 않는다.
- 세부를 다른 문서로 옮길 때 코드·테스트·문서의 인용이 깨지지 않게 한다. 저장소는 ADR을 결정 번호
  ("ADR-013 결정 3")뿐 아니라 **날짜 절 제목**("ADR-013 개정 2026-11-24", 링크 `#결정-갱신-2026-11-25`)으로도 인용한다.
  - 결정 번호는 유지하고 그 자리에 "→ 세부: [문서](링크)" 한 줄을 남긴다.
  - 날짜 절을 옮기면 **같은 제목의 짧은 절**(원칙 1~3줄 + "→ 세부" 링크)을 ADR에 남겨 anchor를 보존한다. 또는 같은 PR에서
    `ADR-NNN (개정|결정 갱신|사실 갱신) <날짜>` 인용을 전부 grep해 새 위치로 고친다.
- 완전히 폐기된 ADR은 제목에 취소선을 긋고(`~~ADR-NNN: ...~~`) 목록 표의 상태 칸에 폐기 사유와 대체
  ADR 번호를 남긴다. 번호는 재사용하지 않는다.

## 목록

| ADR | 제목 | 상태 |
|---|---|---|
| [ADR-001](001-postgresql-as-primary-db.md) | PostgreSQL을 운영 기준 DB로 채택 | accepted |
| [ADR-002](002-dual-check-5min-cutover.md) | 5분 수집 경계의 이중 확인 컷오버(일회성 이전) | accepted |
| [ADR-003](003-unauthenticated-backup-network-restriction.md) | 인증 없는 백업 UI의 네트워크 제한 | superseded by ADR-012 |
| [ADR-004](004-krairport-provider-library.md) | 비행편·주차 현황·주차요금 데이터는 `python-krairport-api`를 provider 라이브러리로 사용 | accepted |
| [ADR-005](005-versioned-rest-api-contract.md) | 백엔드 REST API를 `/v1` 버저닝 + RFC7807 에러로 정식 계약화 | accepted |
| [ADR-006](006-kasi-provider-library.md) | 공휴일 데이터는 `python-kasi-api`를 provider 라이브러리로 사용 | accepted |
| [ADR-007](007-repo-rename-kor-travel-airport.md) | 저장소/패키지/n150 식별자를 `kor-travel-airport`로 개명, 웹앱 브랜드는 `parking-radar` 유지 | accepted (저장소 이름은 ADR-008이 대체, 브랜드 유지 범위는 ADR-011이 좁힘) |
| [ADR-008](008-repo-rename-kor-travel-transport.md) | 통합 교통정보 저장소를 `kor-travel-transport`로 개명하고 운영 리소스는 호환 유지 | accepted (운영 리소스 보류는 ADR-010이 대체) |
| [ADR-009](009-durable-transport-collection-reservations.md) | 교통정보 수집의 짧은 DB 예약과 외부 조회·저장 분리 | accepted |
| [ADR-010](010-deploy-identity-rename-transport.md) | n150 운영 식별자를 `kor-travel-transport`로 옮기고 공항 주차 도메인은 유지 | accepted |
| [ADR-011](011-backend-internal-identity-transport.md) | 백엔드·내부 식별자를 `kor-travel-transport`로 옮기고 사용자 노출 브랜드 `parking-radar`만 남긴다 | accepted |
| [ADR-012](012-admin-token-for-backup-and-admin-routes.md) | 백업·관리 API는 관리자 토큰으로 닫고 공개 웹 앱에서 백업 UI를 없앤다 | accepted |
| [ADR-013](013-internal-service-exports-for-map.md) | kor-travel-map에 OpiNet·KREX·공항 데이터를 토큰으로 닫힌 내부 export로 제공한다 | accepted |
| [ADR-014](014-odroid-host-and-deploy-host-flag.md) | transport 스택을 Odroid에서 운영하고 배포 스크립트는 `--host <addr>`를 효과로 검사한다 | accepted |
| [ADR-015](015-parking-raw-and-statistics-lifetimes.md) | 주차 원본 48시간·집계 통계 영구 보존과 삭제 전 읽기 전환·검산 | accepted |
| [ADR-016](016-reference-export-artifact-lifetime.md) | 기준정보 불변 본문과 유한 HTTP cursor handle 수명 분리 | accepted |
| [ADR-017](017-web-production-runner-non-root.md) | 웹 production runner의 non-root와 역할별 예외 | accepted |

**다음 번호 = ADR-018.**

## 새 ADR 작성 규약

파일명은 `NNN-<slug>.md`, 1개 파일당 1개 결정. 본문은 한두 화면(대략 100줄 이하)을 목표로 하고, 아래 필드를
이 순서로 둔다.

```markdown
# ADR-NNN: <결정을 한 문장으로 요약한 제목>

- **상태**: proposed | accepted | superseded by ADR-XXX
- **날짜**: YYYY-MM-DD
- **결정자**: agent | human | agent + human
- **컨텍스트**: 이 결정이 필요했던 배경과 제약
- **결정**: 실제로 정한 내용 (원칙 수준. 값·필드·절차는 링크)
- **근거**: 왜 이 대안이 맞는지 (버린 대안과 그 이유)
- **결과 (긍정)**: 이 결정으로 얻는 것
- **결과 (부정)**: 이 결정이 치르는 대가·남는 위험
- **후속**: 이 결정을 유지하려면 앞으로 무엇을 확인해야 하는지 (진행 task는 `docs/tasks.md`)
```

영향 범위가 크거나 여러 항목을 한 번에 정하는 ADR은 본문 섹션을 `### 컨텍스트`처럼 실제 h3 헤딩으로
승격하고 표를 섞어 써도 된다. 새 ADR은 다음 번호를 사용하고, 관련 task·문서·테스트와 함께 갱신한다.
