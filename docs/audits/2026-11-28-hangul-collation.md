# 2026-11-28 한글 문자열 정렬 collation 점검

운영 transport DB(PostgreSQL 18.6, 기본 collation libc `en_US.utf8`)에서 공개 유가 시군구 통계가 느린 원인이
한글 키 정렬로 확인됐다(PR #311). 이 문서는 같은 비용이 다른 곳에도 있는지, DB/컬럼 단위로 바꾸면 무엇이
드는지를 로컬에서 직접 잰 결과와 운영 확인 절차를 담는다. 결정 문서는 아니다. 컬럼 collation을 실제로 바꾸면
그때 이 문서를 근거로 PR을 만든다.

## 1. 로컬 측정(운영과 같은 이미지)

환경: WSL Docker `postgres:18`(18.6 Debian, x86_64, 기본 `en_US.utf8`). 운영과 다른 점은 CPU(aarch64)와 호스트 부하뿐이다.
키: 운영 공개 GET에서 받은 실제 시군구 `scope_key` 230개(JSON 배열 한글). 200회 평균.

| collation | 한글 키 230개 정렬 | ASCII 키 230개 정렬 | 순서 |
|---|---:|---:|---|
| 기본 `en_US.utf8`(libc) | 3.50ms | 0.069ms | "전남광주통합특별시 강진군"이 맨 앞 |
| `ko_KR.utf8`(libc, localedef 생성) | 1.40ms | 0.072ms | 가나다(= C 순서) |
| ICU `ko-x-icu` / `und-x-icu` | 0.26 / 0.25ms | 0.08 / 0.07ms | 가나다(= C 순서) |
| 내장 `pg_unicode_fast` | 0.075ms | 0.047ms | 코드포인트 |
| `C` / 내장 `pg_c_utf8` | 0.065ms | 0.04~0.05ms | 코드포인트(한글 음절은 가나다) |

- 한글은 `en_US`가 `C`의 약 54배다. `ko_KR`로 바꿔도 libc라 `C`의 약 21배다. ASCII 값은 규칙 차이가 1.5배 안쪽이다.
- 페이지 쿼리 전체(키 230 × 5유종 × 60일 = 69,000행): 수정 전 33ms → `COLLATE "C"` 수정 후 0.45ms(3회 동일).
- 주유소 시도·시군구 묶음(약 12,000행): 정렬 기반 묶음 `en_US` 207ms / `C` 4ms, 해시 묶음 8ms / 1.9ms.
  로컬 플래너는 해시를 골랐다. 운영 계획은 아래 진단으로 확인한다.
- 같은 문장의 운영 값은 로컬의 수십 배다(운영 C 쿼리 43ms 대 로컬 0.45ms). 정렬 규칙 비율은 운영 진단(기본 대 C 약 45배)과 맞다.
  운영 호스트 자체의 느림은 별도 사안이다.

## 2. DB 기본 collation을 바꾸는 안(권하지 않음)

- DB 기본 collation은 `CREATE DATABASE` 때 정해진다. 바꾸려면 새 DB와 dump/restore, 모든 텍스트 색인 재생성이 필요하다.
  공용 instance이므로 Manager 결정이다.
- `ko_KR.utf8`은 이득이 작다(위 표 1.40ms). 바꾼다면 내장 `C.UTF-8`(`pg_c_utf8`, PG17+) 또는 ICU가 후보다. 내장 provider는
  glibc 업그레이드에 따른 정렬 변화(색인 손상 위험)도 없다.

## 3. 컬럼 단위 `C` 후보

판정: 한글 값 + 공개 경로에서 정렬·묶음·최솟값. 표시 이름(휴게소·터미널 이름, label)은 언어 순서를 유지한다.

| 우선 | 컬럼 | 한글 | 정렬·묶음 위치 | 비고 |
|---|---|---|---|---|
| 1 | `fuel_statistics_daily.scope_key`·`fuel_statistics_history.scope_key` | 예(JSON 배열) | 통계 페이지 정렬·기본 범주(#311 쿼리 단위 처리), 장기 추이 | 기본키 일부. 둘을 함께 바꾼다(서로 join) |
| 2 | `fuel_region_summaries.region_key` | 예(`source:시도:시군구`) | `fuel_regions.py:42` ORDER BY | 기본키 |
| 2 | `fuel_stations.sido_value`·`sigungu_value` | 예 | `fuel_price_distribution.py:216`, `fuel_regions.py:74` GROUP BY·ORDER BY | 운영 계획이 정렬 묶음일 때만 이득. 진단 5로 판단 |
| - | `identity_key`·`*_code`·`source` 등 | 대부분 ASCII | 여러 곳 | 바꾸지 않는다(이득 1.5배 안쪽, 진단 3으로 확인) |

## 4. 컬럼 collation 변경의 비용·주의(로컬 확인)

- `ALTER TABLE fuel_statistics_daily ALTER COLUMN scope_key TYPE varchar(512) COLLATE "C"`: 표를 다시 쓰지 않는다(filenode 동일).
  그 컬럼을 포함한 색인만 다시 만든다. 69,000행 96ms. 그동안 `ACCESS EXCLUSIVE` 잠금으로 읽기도 막힌다. 운영은 표가 더 크고 호스트가
  느리므로 진단 2의 색인 크기로 시간을 추정하고 수집·발행이 없는 때에 한다.
- 기본 collation 컬럼과 비교해도 오류는 없다(기본이 아닌 암시적 collation이 이긴다). 대신 비교가 `C`로 일어나므로 상대 쪽의 기본
  collation 색인을 그 비교에 못 쓸 수 있다. 서로 join하는 컬럼은 함께 바꾼다.
- 모델은 `String(n).with_variant(String(n, collation="C"), "postgresql")`처럼 PostgreSQL에만 지정한다(SQLite는 "C" collation이
  없다). `alembic check`가 모델과 migration 차이를 잡는다.
- 정렬 순서가 바뀌는 응답(목록·기본 선택·ETag)은 PR에 적는다. #311로 시군구 통계는 이미 바뀌었다.

## 5. 운영 확인(읽기 전용)

`scripts/diagnostics/collation-hangul-readonly.sql`. `BEGIN READ ONLY` 안에서 다음을 본다. 로컬 PG18에서 끝까지 실행해 확인했다.

1. 서버 버전·DB collation·glibc collation 버전 일치 여부
2. 후보 컬럼의 현재 collation·표/색인 크기(재생성 비용 추정)
3. 후보 컬럼의 비 ASCII 비율(표본 2,000행)
4. 운영 호스트에서 같은 한글 키 4,600행 정렬: 기본 / C / ICU(로컬 409 / 14 / 21ms)
5. `pg_stat_statements`가 있으면 정렬·묶음이 든 문장의 평균·최대 시간 상위 25개. 없으면 backend `slow_request` 로그로 대신한다.

2026-11-28 현재 이 저장소 작업 환경의 운영 키는 Odroid(.13)·n150(.14) SSH에서 거부되어 운영 실행은 접근 권한이 있는 쪽이 한다.
