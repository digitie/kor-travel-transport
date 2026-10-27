# 원본 JSON scalar 변환 CPU 후보 — 2026-10-26

## 2026-10-27 최신 운영 상태

PR #138의 최종 CI·두 리뷰·머지 뒤 최신3691 운영 소스와 공개 HTTPS UI32를 수용했다.
아래 국소 합성 계량과 실제 수집 전체 CPU/RSS 효과는 구분한다. 후자는 아직 확정하지 않았다.
[최종 배포·UI·자연 수집 관측](2026-10-27-integrated-production-rollout.md). 아래 미배포 표현은 당시 이력이다.


## 구현·순수 계량 체크포인트

제품은 `_plain_json` 시작에 정확 `type is`/`None is` 분기6줄만 추가했다. 다른 함수와
기존 Mapping→list/tuple/set→datetime→date→Decimal→`.value` 순서는 바꾸지 않았다.
그6줄을 역제거하면 기준 source 전체가 동일하며 API·DTO·SQL·provider pin은 변경0이다.

원본/후보 각각 실제 collector module 경로와 SHA를 결박한 계약31개가 모두 통과했다
(원본31PASS/3.44초, 후보31PASS/3.72초). builtin identity와 NaN/무한대·음수0,
str/int/float subclass와 Enum·Mapping을 겸한 str subclass, Mapping key와 삽입 순서,
컨테이너 복사·별칭, UTC 변환/naive UTC·Decimal 표기, Pydantic JSON mode/직접 모델 identity,
미지 객체·`.value` 별칭과 원래 예외 객체를 대조했다. 외부 network 차단 hook의 호출0도
확인했다. 이31개는 순수 함수 계약이며 전체 수집·DB/API 통합 검증의 대체가 아니다.

기존 로컬 venv는 현재 main의 Opinet/KRIC public symbol이 없어 기본 collector/conftest
import가 실패했다. 원 실패를 보존하고 정확 f58a879 Opinet source archive를 PYTHONPATH에
추가해 이 순수 모듈만 `--noconftest`로 실행했다. 기존 환경·provider 제품을 고치지 않았고
정확 lock 전체 CI·기존 전체 backend/PG·Docker·live UI는 아직 수용하지 않았다.
새 시험 파일은 backend 작업 디렉터리 기준 Ruff PASS다. 무관한 CWD의 전역 Ruff 규칙은
기존 source에 이미 있던 import/예외 처리도 보고하므로 그 결과를 저장소 전체 실패/성공으로
해석하지 않았다. 원래 검사 규칙을 바꾸거나 주변 코드를 정리하지 않았다.

Python3.13.14/Linux x86_64의 별도 프로세스에서 원본/후보를 교대3쌍 측정했다.
함수 source는 Git 기준 원문과 위6줄 후보의 AST에 정확히 결박했다. 각 표본은 입력 생성·
import·warmup·JSON 인코딩을 제외하고 normalizer12회만 계량했다. scalar bulk는33,000개,
중첩 bulk는합성 원본/가격/시각/Enum을 포함한1,000행이다. 네트워크·DB·실제 provider 호출은0이다.

| CPU 중앙값 / normalizer12회 | 원본 | 후보 | 감소율 |
| --- | ---: | ---: | ---: |
| scalar bulk | 95.978ms | 20.024ms | 79.1% |
| 중첩 bulk | 143.980ms | 108.001ms | 25.0% |

각 workload의 모든 표본에서 JSON bytes와 synthetic payload hash가 같았다. 프로세스 생애
peakRSS 중앙값(KiB)은 scalar25,340→25,364 / 중첩27,356→27,352로 사실상 같으므로
메모리 개선은 주장하지 않는다. RSS는 함수 전용 peak가 아니며 CPU 절감률도 ARM·전체
수집·idle CPU 절감률이 아니다. 저장된 운영 profile·원래 실패와 혼합하지 않는다.

순수 계량 원장은 `transport-plain-json-scalar-paired-bench-r1.json`이고 SHA는 아래 최종
source checkpoint에 결박한다. 재검산 중 standalone benchmark CLI를 import해 순수 계량이
추가 실행된 검사 실수는 별도 보존했으며 원 O_EXCL 결과는 덮어쓰지 않았다. 그 추가 표본은
수용 수치에 포함하지 않는다. 이후 검산은 실행 없이 AST만 읽어 candidate 동등성을 확인했다.

현재 Draft PR #138의 작은 코드 후보이며 두 독립 적대리뷰·최종 CI·live UI·머지·운영 적용은
미완이다. 원본 저장소의 미커밋 파일과 기존 검증 이력은 그대로 보존했다.

## 초기 설계 기록 (첫 문서 커밋 당시)

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

초기 설계 커밋 당시에는 문서만 추가했고 코드·측정·CI·운영 적용은 실행하지 않았다.
