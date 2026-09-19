# ADR — 결정 기록

이 디렉터리는 데이터 모델·배포·운영 안전성처럼 되돌림 비용이 큰 결정을 기록한다. ADR은
"프로그램 핵심 구조"(DB/스택 선택, 데이터 이전·컷오버 방식, 인증·네트워크 경계 같은 운영 모델)
결정만 다룬다. 특정 기능의 세부 구현 규칙이나 순수 프로세스 규칙은 ADR로 남기지 않고
`AGENTS.md`/`SKILL.md` 또는 관련 `docs/architecture/*`, `docs/runbooks/*` 문서에 둔다.

## 목록

| ADR | 제목 | 상태 |
|---|---|---|
| [ADR-001](</F:/dev/kor-travel-airport/docs/adr/001-postgresql-as-primary-db.md>) | PostgreSQL을 운영 기준 DB로 채택 | accepted |
| [ADR-002](</F:/dev/kor-travel-airport/docs/adr/002-dual-check-5min-cutover.md>) | 5분 수집 경계의 이중 확인 컷오버 | accepted |
| [ADR-003](</F:/dev/kor-travel-airport/docs/adr/003-unauthenticated-backup-network-restriction.md>) | 인증 없는 백업 UI의 네트워크 제한 | accepted |
| [ADR-004](</F:/dev/kor-travel-airport/docs/adr/004-krairport-provider-library.md>) | 비행편·주차 현황·주차요금 데이터는 `python-krairport-api`를 provider 라이브러리로 사용 | accepted (주차는 구현 완료, 비행편은 미완료) |
| [ADR-005](</F:/dev/kor-travel-airport/docs/adr/005-versioned-rest-api-contract.md>) | 백엔드 REST API를 `/v1` 버저닝 + RFC7807 에러로 정식 계약화 | accepted |
| [ADR-006](</F:/dev/kor-travel-airport/docs/adr/006-kasi-provider-library.md>) | 공휴일 데이터는 `python-kasi-api`를 provider 라이브러리로 사용 | accepted |
| [ADR-007](</F:/dev/kor-travel-airport/docs/adr/007-repo-rename-kor-travel-airport.md>) | 저장소/패키지/n150 식별자를 `kor-travel-airport`로 개명, 웹앱 브랜드는 `parking-radar` 유지 | accepted |
| [ADR-008](008-repo-rename-kor-travel-transport.md) | 통합 교통정보 저장소를 `kor-travel-transport`로 개명하고 운영 리소스는 호환 유지 | accepted |

**다음 번호 = ADR-009.**

## 새 ADR 작성 규약

파일명은 `NNN-<slug>.md`, 1개 파일당 1개 결정. 본문은 아래 필드를 이 순서로 둔다.

```markdown
# ADR-NNN: <결정을 한 문장으로 요약한 제목>

- **상태**: proposed | accepted | superseded by ADR-XXX
- **날짜**: YYYY-MM-DD
- **결정자**: agent | human | agent + human
- **컨텍스트**: 이 결정이 필요했던 배경과 제약
- **결정**: 실제로 정한 내용
- **근거**: 왜 이 대안이 맞는지 (대안 비교는 여기에 녹여서 서술)
- **결과 (긍정)**: 이 결정으로 얻는 것
- **결과 (부정)**: 이 결정이 치르는 대가·남는 위험
- **후속**: 이 결정을 유지하려면 앞으로 무엇을 확인/갱신해야 하는지
```

영향 범위가 크거나 여러 항목을 한 번에 바꾸는 ADR은 본문 섹션을 `### 컨텍스트`처럼 실제
h3 헤딩으로 승격하고 표를 섞어 써도 된다.

## 상태 변경 규칙

- 결정이 뒤집혀도 원 ADR 본문은 지우지 않는다. `상태`를 `superseded by ADR-XXX`로 바꾸고
  새 ADR을 추가한다.
- 완전히 폐기된 ADR은 제목에 취소선을 긋고(`~~ADR-NNN: ...~~`) 위 목록 표의 "상태" 칸에
  폐기 사유와 대체 ADR 번호를 남긴다. 번호는 재사용하지 않는다.

새 ADR은 다음 번호를 사용하고, 관련 task·문서·테스트와 함께 갱신한다.
