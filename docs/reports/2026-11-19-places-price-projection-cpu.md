# 혼합 장소 가격 투영 CPU 후속 — 2026-11-19

## 실제 기준과 범위

- 기준 소스는 `defc4a7e3141f7b5ea4a83a5a4b70c7fc46526d8`, DB head는 0044다.
- 부모의 실제 quiet 측정: places limit5000 중앙값 2544.42ms로 1초 목표 미달,
  rail304 5개 p95 106.896ms로 300ms 목표 충족. TRN04는 재구축 밖 기준 미입증으로 INCONCLUSIVE다.
- 기존 `validated_place_map_items`는 현재 DB 입력 전체 바이트 일치를 확인한다.
  로컬 반복 요청에서도 실제 cache hit였으므로 DTO 재검증을 운영 지연의 원인으로 단정하지 않는다.
- 혼합 장소의 유가 조립만 바꾼다. SQLAlchemy 가격 Row의 속성을 반복 조회하지 않고,
  명시한 6개 SELECT 열을 한 번 풀어 현재 요청의 가격 dict를 만든다.
  B027 우선·없을 때 정렬 첫 유종·NULL·0·Decimal·UTC 변환은 유지한다.

## 같은 fixture의 로컬 증거

운영 복제나 운영 HTTP 측정이 아닌 기존 합성 PostgreSQL fixture다.
limit5000에서 실제 반환은 2670개·약 2.02MB다.

| 측정 | 기존 defc | 후보 |
|---|---:|---:|
| 가격 625곳·3125행 조립 CPU 중앙값, 24개 교대 표본 | 12.45ms | 5.60ms |
| 전체 HTTP CPU 중앙값, 준비 3쌍 제외 14개 교대 표본 | 69.03ms | 61.43ms |
| 전체 HTTP 벽시계 중앙값 | 163.58ms | 153.42ms |
| SQL 개수 | 6 | 6 |

- 본문은 generated_at 제외 전체 동등하다. 가격 단계는 JSON bytes와 SHA256도 동일하다.
- 원문 및 도구는 저장소 밖 전용 `transport-places-dto-followup-work`의
  `price-paired.json`, `route-paired.json`, `baseline-profile.txt`에 보존했다.
  HTTP 최종 비교는 집중 테스트 종료 후 별도로 실행했다.
- 운영 1초 달성·운영 CPU 개선율·cold SQL 개선을 증명한 결과가 아니다.
  SQL 6회·DB 반환량·현재 입력의 JSON 생성·기존 검증 캐시 경계는 그대로 남는다.

## 검증과 다음 단계

- WSL 전용 PostgreSQL을 기존 로컬 PG에 따로 만들고 Alembic head0044까지 적용했다.
- 기존 관련 77개 PASS. 추가한 가격 순서·B027 없는 fallback·NULL·0·빈 가격·UTC
  5개 parameter case도 PASS다(별도 실행, 중복 없는 총82개).
  최초 추가 fixture의 필수 지역 필드 누락 5개 실패는 보존하고 fixture만 보완했다.
- OpenAPI 정본 확인 PASS. 전체 backend suite와 새 이미지/운영 실행은 하지 않았다.
- TTL·mixed 응답 본문 캐시·revision 범위 확대·DDL·의존성·frontend 변경은 없다.
  출처·신선도·가격 갱신·삭제·돌발24시간은 기존 요청별 DB 경로를 유지한다.
- 정확한 후보 CI와 독립 검토 뒤 정상 캐시 빌드 및 실제 성능을 다시 수용해야 한다.
  후속 운영 설정은 실제 설치 PASS가 확인된 Manager efda를 기준으로 새로 바인딩한다.
