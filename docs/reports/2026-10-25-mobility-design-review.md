# 교통·날씨 조사/설계 문서 검토 기록

대상: [조사](../research/2026-10-25-mobility-ux.md), [설계](../design/2026-10-25-mobility-improvements.md),
[Weather 조사](https://github.com/digitie/kor-travel-weather/blob/main/docs/research/2026-10-25-weather-ux.md),
[Weather 설계](https://github.com/digitie/kor-travel-weather/blob/main/docs/design/2026-10-25-weather-map-improvements.md).
기능 소스 기준은 Transport `a93dfba`, Weather `d4e5aa2`, Map `c06345841`, Common 참조 `294e0dfc`다.

## 검토 범위와 예외

사용자는 사전 조사·설계 문서만 작성한 뒤 두 번 정리하고 적대적 리뷰어 1명에게 검토받아
문서 PR을 CI 결과 없이 머지하도록 요청했다. 이 예외는 이번 문서 PR에만 적용한다.
후속 기능 구현의 테스트·CI·리뷰·배포 게이트를 면제하지 않는다.

## 1차 정리 — 요구·근거·현재 사실

- 8개 요청과 추가 이용 상황·취향을 설계 작업 ID에 연결했다. 단순 지표 개수나 소비자 앱 전체 복제를 목표로 두지 않았다.
- 이미 존재하는 overlay, 공항 job/schedule, 품질/시설 flag, 주유소 이력 export를 대조해 중복 구현 계획을 피했다.
- 주차 `outlook` 조회 집계와 기존 analytics cache, 일반철도 TAGO와 도시철도 KRIC를 구분했다.
- 가격 미변동과 수집 공백의 차이, 캐시 기본 10분과 화면 요구 30분의 차이를 보완했다.
- 운영 치수·실제 시간표/주차 원인은 미검증으로 남기고 소스 존재를 운영 수용으로 표시하지 않았다.

## 2차 정리 — 저장소 간 계약·링크·상태

- 양쪽 C-MAP-01·W-UX-01~03와 Transport 작업 원장, 같은 화면 치수·프로젝트 토큰·API 재사용 경계를 대조했다.
- API 표의 축약 경로를 `/v1` 기준으로 정리하고 교차 저장소 링크를 삭제 예정 branch 대신 main 문서 경로로 맞췄다.
- 신규 보고서 6개의 링크 목록 71개를 추출해 로컬·교차 저장소 문서 대상 존재를 확인했다(추가 품질 자료 링크는 후속 확인).
  외부 URL의 모든 실시간 가용성을 일괄 검증했다는 뜻은 아니다. 확인 방식/실패한 자료는 조사에 명시했다.
- 양쪽 각각 Markdown 7개 변경만 확인했고 `git diff --check`가 통과했다. 코드/잠금/설정/운영 파일 변경은 없다.
- native 런타임·운영 미측정, 설계 가설·새 수용 목표, 향후 기능 게이트와 이번 문서 예외를 다시 구분했다.

## 독립 적대적 리뷰

Popper 1명이 Transport `c2afaaf`/Weather `c4783d7`을 독립 읽기 전용 검토했다. P0/P1은 없고 Weather P2 1건을 지적했다.
‘등록하지 않은 장소’가 즐겨찾기인지 DB location인지 모호하고 이름→좌표→저장 anchor·필터/부재 연결이 빠진 문제다.
현재 nearby/resolve에는 provider/kind가 없음을 소스에서 재확인하고, Weather 설계·조사·W-UX-03에
기존 Geo 검색 계약 검증/지도 지점 대안·대표성/부재·정렬/LIMIT 전 필터·자동등록/추가 수집 없음과 수용 시나리오를 보완했다.
동일 리뷰어가 Transport `10f37d8073a8b038498f3b7ef0e0f00a0fe5c29b`/Weather `abc05abe271188559c1255970691a5cc83c9c2ce`를
재검토해 **PASS, 기존 P2 해소·잔여 P0/P1/P2 없음**을 확인했다. 리뷰어는 파일·앱·빌드·서비스·외부 PR을 변경하지 않았다.
이후 변경은 이 결과·완료 원장·인수인계 정산뿐이며 기능 설계는 바꾸지 않았다.

문서 Draft PR: [Transport #130](https://github.com/digitie/kor-travel-transport/pull/130),
[Weather #168](https://github.com/digitie/kor-travel-weather/pull/168). 두 PR 모두 문서 변경만 포함한다.
최종 머지 상태·SHA는 두 PR의 GitHub 메타데이터가 정본이다. 이번 문서 PR은 사용자 지시대로 CI 결과를 기다리지 않는다.

## 최종 문서 검증

신규 조사/설계/검토 문서에서 양쪽 각각 상대 링크 6개·교차 저장소 링크 3개를 검사해 대상 파일 존재를 확인했다.
외부 참조 목록은 Transport 42개·Weather 16개이며 전체 URL 실시간 가용성 검사는 아니다.
최종 정산은 양쪽 각각 Markdown 8개이며 기능/설정/잠금 파일이 없고 `git diff --check`를 통과했다.

## 실행하지 않은 검증

문서 전용이므로 애플리케이션 테스트·빌드·Docker·운영 배포를 실행하지 않는다.
공식 앱은 설치/런타임 시험하지 않았고 Weather 운영 지도는 로그인 이후 미측정이다.
문서의 시나리오는 후속 구현 수용 조건이며 현재 통과 결과가 아니다.
