# 신고된 교통 화면·수집 문제 정산

## 실제 버전 차이와 우선 복구

지도 타일·유종 전체·주차 분석 날짜·유가 극값/최저가10곳·필터 배치 신고를 구분해 조사했다.
공개 웹은 main `d9d4559c02076975c80b688410591da0106b5873`인데 API/수집기는
`499822601abca3f050aa0cfe0e27fb446d22281d`였다. 구 API는 ALL의 items/history가0이고
단일 유종 이력은7일·극값 필드 없음이었다. 최초 읽기 JSON은 후속 관측으로 덮였으므로
그 원 파일의 시각·해시를 보존했다고 주장하지 않으며 실제 최초 stdout과 요약을 남긴다.

사용자의 재배포 지시에 따라 이미 준비된 d9 ARM64 이미지를 API/CS에 반영했다. 첫 부모는
이미지 기본 Python 버전/해시를 사용자 env 변경으로 간주해 교체 전에 exit1이었다. 모든
자식 종료·기존5 CID 동일을 확인하고 순수 이미지 기본 메타데이터만 허용한 고유 R2로 진행했다.
R2 첫 Invocation의 done·Main0·cgroup 부재·70개 소유 자식 종료, schema0042·원20일정 복원·
Manager healthy·다른 서비스/웹/키/env 보존을 확인했다. 백업·복원은 사용자 지시로 생략했다.

그 뒤 실제 ALL은5유종/95개 저장 일별행, 단일 유종은19개 저장일과 최저·최고 필드가
돌아왔다. PC1440/모바일375에서 실제 다중 선/극값을 확인했다. 30일 창에19개 저장일인 것을
30일 연속 관측으로 바꾸지 않는다. 지도는 두 화면에서 정상 PNG 타일24개·오류 배너0이고
사용자도 오류가 사라졌다고 확인했다. 타일용 추정 코드 변경은 추가하지 않았다.

## 주차 날짜가 멈춘 원인과 공급자 수정

운영 김포5·김해3·제주3곳은 실제 관측이11월3일이었다. 인천19곳은11월13일 이력이 있지만
정규 수집은 partial_success였다. 새 읽기 진단에서 기존 KAC HTTP 서버의 연결 거부를
확인했고, 실제 인천 원문19행의 `datetm`은14자리 뒤 `.000` 형식이었다. 구 strict 파서는
이를 거부했다. 과거 오류 문자열만으로 과거 stack을 복원했다고 주장하지 않는다.

공식 [한국공항공사 전국공항 실시간 주차정보_GW](https://www.data.go.kr/data/15158681/openapi.do)의
HTTPS `/B551178/parking-realtime-status/info`를 확인했다. 최초 보관 키는403/30이었고
사용자의 활용신청 완료 뒤 단1회 재확인에서00/NORMAL SERVICE·실제25행을 받았다.
이 진단은 DB 쓰기·수집 성공 기록이 없는 읽기이며 운영 수집 최신화 완료가 아니다.

공급자 [python-krairport-api PR14](https://github.com/digitie/python-krairport-api/pull/14)를
두 독립 검토·정확 HEAD CI4개 성공 뒤 main `6b81cc7f8ee46fb26375f5c91fb5ed94c182e376`으로
머지했다. Transport는 검증된 제품 커밋 `b146b6ac85169c069bbe0119e3892a6006f7abcb`을 정확히
소비한다. KAC 주차 전용 두 호출만 GW로 옮기고 generic raw/다른 서비스 주소는 보존한다.
IIAC는 정확 `.000`만 허용하며 잘못된 시각·비영 소수부·대수 검증·원문·초·KST를 보존한다.
공급자 WSL356PASS/14subtests·coverage92.85%, network:none Docker 집중154PASS와 정적 검사0이다.
Transport 소비 계약24개도 WSL SQLite/PG18와 Docker PG18에서 각각 통과했다. 중복 합산하지 않는다.

## 화면·통계 보완과 현재 한계

- [유가 정산](2026-11-13-fuel-statistics-reported-regressions.md): 동결된 현재 전국/고속도로 전체
  세대의 완전한 point를 검산해 구 Top10을 읽기 전용 보완한다. 과거 지역 membership은 없으므로
  현재 주소로 추정하지 않으며 불완전 순위·과거 누락 극값을 미제공으로 남긴다.
- [공항 분석 정산](2026-11-13-airport-analytics-refresh-regression.md): 보이는 화면의60초/복귀
  재조회·중복 요청 방지와 숨은 차트 최초 마운트 문제를 수정한다. 관측 시각 자체는 바꾸지 않는다.
- 독립 James 검토의 글씨200% PC 필터 잘림은620px container 경계를38.75rem으로 바꿔 해결했다.
  실제 Chromium1440/1024·글씨200% 두 조건에서 교체 전 잘림과 교체 후 오른쪽 새로고침/overflow0을
  검산하고 캡처를 직접 확인했다. 합성100곳/30일 fixture이며 운영 가격 수용으로 대체하지 않는다.

독립 James의 숨은 엔진 경계는 범위별 실제 관측 방문 상태와 canvas의 양수 크기 확인으로
보완했다. 범위 교체·최초 빈 응답·숨김 복귀와 history 상태를 포함한 WSL/Docker 각25개가
통과했다. 앞선 hook22·view 검증과 겹치는 수는 합산하지 않는다. 최종 공개 소스를 공식 npm
pack으로 admin의 파일 패키지에 다시 반영하고 typegen/타입/공통 의존성 검사를 별도로 통과했다.
두 독립 검토의 최종 delta에서 새 확정 P0/P1/P2는 없었다. main PR195는 CI 정책 참조만
바꾸며 제품 런타임 변경이 아니다.

## 최종 머지·이미지·실제 수용

Transport PR196은 정확 통합 HEAD `dcbe25a3715f6ad1d43bed4e2f04b766f992cf1a`의
backend/frontend/admin CI와 두 독립 검토 뒤 main `49c1688d22a1469f7c7a834c5d72f98653eb12b9`로
머지했다. backend는1918PASS/2SKIP/54subtests였고 CI live-e2e는 생략이다. 아래 실제 브라우저
수용과 구분한다. main과 이미지 입력의 차이는 공통 CI 참조 파일1개뿐이며 런타임 트리는 같다.

API·CS는 ARM64 `8a9d38e7f84369d3de1936d6ba9dc3ae4b4710767331365aa02dce9104def709`,
관리자는 `588b36d3cec18809968492494cd0a71fb5d157316a9d30be4d356a529eb74329`로 반영했다.
SDKb146의 실제 설치·원문 파싱·정확 아카이브 및 Git 정규화 지문·비공개 지도 키 소비를 검산했다.
성공한 backend/admin 이미지는 후속 보조 검산 오류 때문에 재빌드하지 않고 재사용했다.
schema0042와 원20일정 복원·5역할 healthy·Manager adopt/verify/show healthy, 명시적 env·키·
기존 공개 frontend/gateway·Weather/Geo/공용 daemon을 보존했다. DB migration·수동 수집·재집계·
백업/복원·원본 삭제는 없다.

최종 forward의 첫 Invocation `03cecb010aea48be8b9139c21eb73458`은 실제 done/exit0·Main0·
cgroup 부재·68개 소유 자식 종료다. API/admin은 선행 교체 결과를 그대로 쓰고 CS만 이어서
교체했다. 사용자의 후속 직접 지시 “강제 중지하고 올려”에 따라 정확히 식별한 KRIC1건만
Dagster SAFE_TERMINATE로 정산했다. 공식 CANCELED/앱 failed이며 기존 원문374개와 모든
본문 지문이 동일하다. 다른 수집 취소·수집기 OS kill은 없다. 선행 배포 부모는 deferred SIGTERM
정산으로 실제 exit1·원20복원·220개 자식 종료이며 이를 성공0으로 바꾸지 않는다.
초기 sender·Manager 변경·NVMe 경로 오인·builder 선택·복사 권한·CRLF 검산 오류의 각 실패
원문도 보존한다. 최종 native 검산 전용 R7은 실제0이며 이 문서 갱신으로 제품을 재빌드하지 않는다.

### 정규 공항 수집과 날짜 복구

원20일정 복원 뒤 정상 `airport_collection_job` 두 실행이 실제 SUCCESS로 끝났다.
앱10567/공식 `164bae74-bf73-4129-a6af-aa7ec6e8465a`, 앱10569/공식
`6e03224b-64c9-4b9c-a9d4-3dfb29a6b7be`에서 각각44개 주차 관측을 DB에 저장했다.
KAC·인천 주차·요금 원문 HTTP200과 parse_error 부재를 실제 DB에서 확인했다. 과거 부분 성공은
보존한다. 진단용25행 응답을 수집 성공으로 대체한 것이 아니다.

13:59UTC 읽기에서 김포5·김해3·제주3개 주차장의 현재 관측은 모두
`2026-11-13T13:57:03Z`, 인천19개는 `13:56:00Z`다. 이후 실제 김포 분석 API는 HTTP200,
관측이 있는 두 버킷 `14:00:00Z`/`14:03:03Z`와 각5개 주차장의 잔여1303/1391면을 반환했다.
generated_at을 관측 날짜로 쓰지 않았다. 실제 Chromium156 PC1440/모바일375에서
`11/13 (금)` 날짜 선택과 가시 line canvas·문서 overflow0·pageerror0·logout303·소유 자식0을
확인하고 캡처를 검토했다. 복구 전 단절 구간을 임의 보간·backfill하지 않는다.
이 관측은 새 날짜·자료·가시 엔진 수용이다. 별도 실제 터치375 문맥에서 차트 shell의 폭이
1180px이고 자체 가로 스크롤이0인 현상도 관측했다. 문서 overflow0을 모든 축/컨트롤의 모바일
가시성 보장으로 확대하지 않으며 해당 폭/스크롤 문제는 별도 화면 후속으로 남긴다.

### 지도·유가와 남은 한계

새 관리자에서도 PC/모바일 정상 지도 타일24개·오류 배너0, ALL5유종·95개 실제 저장 일별행과
각 유종 Top10을 확인했다. 실제 hover/모바일 touch 설명창에 날짜·평균·최저·최고·지도 링크가
나오며 오른쪽 새로고침/유종별50개 표 행을 확인했다. 30일 창의19개 저장일을 연속30일 자료로
과장하지 않는다. 비어 있는 과거 지역 membership과 누락 극값은 여전히 미제공이다.
전체 조회7.61초 등은 단일 표본이며 p95/1초 보장이 아니다.

브라우저 보조 관측의 로그인 반환 경로·가시 패널 선택자 오인·이미 방문한 숨은 heatmap6개를
미방문 daily 엔진으로 잘못 센 실패는 원문을 보존했다. 실제 daily 전용 경계와 별도 가시 DOM을
확인했으며 제품 코드를 바꾸거나 원 실패를 PASS로 덮지 않았다. 항공편은 여전히 제공기관
출도착 페이지 중복 오류/0편을 표시한다. 주차 관측 복구를 항공편 복구로 확대하지 않는다.

정본 원장은 Git 밖 `transport-reported-regressions-20261113/plan.json`과
`fix-deployment-forward/{last-status,terminal-observation}.json`, `parking-db-after-fix.json`,
`parking-official-normal-runs.json`, `parking-final-analytics-api.json`,
`live-fixed-parking-r5/results.json`, `live-fixed-api-first/results.json`이다.
실제 터치 문맥의 별도 폭/스크롤 원문은 `live-fixed-parking-mobile-detail/results.json`이다.
