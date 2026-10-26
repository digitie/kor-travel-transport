# 원본 JSON scalar 변환 CPU 후보 — 2026-10-26

## 설계 초안과 수용 경계

기준 main은 `71a551ef7fa29957be018294363063e1870be011`이다. 운영의 15초·10Hz
nonblocking GIL 관측에서 Transport 117표본 중 `_plain_json` 14표본 이상과 JSON encoder,
`model_dump`가 나타났다. 표본 가중치는 CPU 계량초가 아니며 전체 수집·idle CPU 원인을
확정하지 않는다. 원본 profile·argv는 저장하지 않았고 정제 관측 원장 SHA는
`670bf8ffa6cde923fe1899d4685620a89d3f233d58f38fc770a45a4062a05551`이다.

작은 후보는 `_plain_json`의 정확한 builtin `str`, `int`, `float`, `bool`, `None`만
Mapping/ABC 검사 전에 반환하는 것이다. `isinstance(value, str)` 같은 넓은 분기는
사용하지 않는다. Enum과 scalar subclass, datetime/date, Decimal, Mapping, 컨테이너 순서,
오류와 알 수 없는 객체의 `.value`/identity 계약은 그대로 보존한다. `_provider_json`의
`model_dump(mode="json")`과 provider 원본 입력·DB/API/DTO/SQL 경계도 바꾸지 않는다.

Map에서 중복 변환·검증을 줄인 후속 전파 범위이며, Map 전용 SQL/guard를 복제하거나
이 한 함수 때문에 Common 추상화를 추가하지 않는다.

## 실행 순서

1. 기존 호출과 SDK payload를 대조하고 기존 결과·오류·identity 계약 회귀를 고정한다.
2. source의 기존 함수와 최소 후보를 독립 프로세스에서 교대로 실행해 scalar 및 중첩
   대표 bulk의 CPU/wall/RSS와 JSON bytes를 비교한다. 단일 함수 비용이며 네트워크·DB·
   실제 수집 전체 효과로 확대하지 않는다.
3. 의미가 보존되고 국소 CPU 절감이 관측될 때만 작은 코드 커밋을 추가한다. 효과가 없거나
   의미가 불명확하면 제품 변경 없이 결과를 보고한다.
4. 집중 검증과 독립 적대리뷰 두 개를 받는다. 전체 CI·live UI·머지·배포는 별도 미완 gate다.

현재는 설계 문서만 추가했다. 코드·측정·CI·운영 적용은 아직 실행하지 않았다.
