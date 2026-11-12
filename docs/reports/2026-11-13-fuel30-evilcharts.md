# 유가 30일·전체 유종·EvilCharts 구현 검증

## 반영 범위

사용자 요청 12~15를 유가 API·집계·관리 UI에 반영한다. 유가 통계는 30일 평균 선과 최저/최고 whisker, 모든 유종을 한 그래프로 표시한다. 범위·유종·추이 제어는 같은 행이고 모바일에서만 접힌다. 수집 기준은 작은 한 줄이며 통계 요약 박스를 제거해 그래프를 먼저 둔다. 가격순 최대 10곳과 주소 지도 링크는 휘발유·경유·고급유·LPG, 기존 등유 순서다.

주유소 상세는 현재 유효 가격 한 줄→30일 차트→주소/연락처/위치 근거→관측값 표 순서다. 실제 관측과 현재 읽기 모델 가격의 기준 시각이 다를 수 있음을 유지한다. i 안내에서 오래된 가격을 확인할 수 있다. 시간축은 실제 KST 간격이고 빈 날짜는 연결하거나 보간하지 않는다.

공식 EvilCharts의 Apache ECharts line/공용 소스 6개와 MIT를 재사용한다. 단순히 자체 ECharts wrapper에 이름을 붙이지 않는다. 앱의 시간축·whisker·툴팁은 공식 컴포넌트 chartOptions 확장점에 전달한다. 설치 출처와 원문/설치 SHA는 `vendor/evilcharts-fuel.json`에 있다. 공용 범례의 클릭 div만 native button으로 바꾸고 전체 표시의 aria-pressed를 보정했다. 그래프 키보드 날짜 선택도 native Button으로 제공한다. 일반 철도/해운 상세는 실제 유가 그래프가 생성되기 전까지 무거운 엔진을 적재하지 않는다.

## 데이터 보존과 읽기 계약

- 통계 API의 기존 B027 기본값은 유지하고 ALL을 추가한다. 공개 포인터·현재 범주·선택 범주의 30일 이력을 한 SQL snapshot에서 읽는다. ALL의 중복 범주 키는 DISTINCT로 제거하여 PostgreSQL scalar subquery가 여러 행을 반환하지 않게 한다.
- 일별 history에 product_code·minimum_price·maximum_price·cheapest_station을 추가한다. 해당 날짜에 저장된 값만 읽으며 없으면 null이다. 현재 최저가나 극값을 과거 날짜에 대입하지 않는다.
- 이번 성공 수집 시각과 FuelLatestPrice.collected_at이 같은 양수 가격만 게시하는 기준은 같다. 정상 게시 때 범주·유종별 10곳만 메모리에 유지해 순위를 저장한다. 이름/주소/좌표도 그 세대의 값을 함께 보존하므로 이후 기준정보 변경으로 과거 순위가 바뀌지 않는다.
- 과거 집계에 순위 배열이 없으면 기존에 알려진 cheapest_station+minimum_price 한 곳을 유지하고 추가 순위 미저장을 안내한다. 10곳을 가진 것처럼 꾸미거나 현재 가격을 이용해 과거 모집단을 재구성하지 않는다. 정상적인 다음 수집부터 순위가 축적된다.
- 일별/지역 집계는 영구 보존하며 조회 창만 30일이다. 개별 가격 이력 API는 기존 기본 7일을 유지하고 최대 30일을 허용한다. UI는 30일을 명시한다. cursor 창·revision·409 재시작·실패/미지원 원천은 기존대로 구분한다.
- 신규 마이그레이션 파일·운영 migration·원본/과거 세대 수정·운영 재수집/수동 게시·정리·prune·백업/복원 실행은 없다. 격리 시험 DB에는 기존 Alembic head만 설치했다. 운영/API 서버 배포 및 이미지/프로덕션 빌드도 없다.

## 검증

| 환경 | 결과 | 확인한 내용 |
| --- | --- | --- |
| WSL SQLite | 24개 통과, 413.94초 | 30일 경계·ALL·실제 극값/null·가격순 10곳·이전 수집 제외·과거 주소·오류/원본 보존·native 이력 |
| WSL PostgreSQL 18 | 24개 통과, 353.30초 | 격리 DB의 실제 SQL·API 계약 |
| WSL+Docker PostgreSQL 18 | 24개 통과, 312.51초 | 같은 집중 시험, 종료 후 정확 소유 CID/label 검산·테스트 DB 제거 |
| WSL/Docker admin | 각각 46개 통과 | 전체 유종·지표 누락·툴팁 수치/안전한 HTML·날짜 공백·주소 링크·순위·기존 오류/취소·상세 순서 |
| 최종 접근성/strict lint | 정산 중 | vendor 범례와 그래프 native 키보드 제어를 포함한 마지막 회귀 |
| TypeScript | 0 오류 | 변경 컴포넌트와 API 소비 타입 |
| Chromium 156.0.8078.4, 1440/375 | fixture 실제 캔버스 통과 | 2개 시간축 차트, 5유종×30일 선/whisker, 마우스/클릭 툴팁, 정확 금액·지도 링크, 각 10행 표, 원본 표 마지막, 현재가격 우선, pageerror0·가로 overflow0 |

각 환경은 같은 시험을 반복한 것이므로 숫자를 합산하지 않는다. 브라우저는 격리 fixture이고 운영 API·실제 로그인·DB를 함께 검증한 live E2E 증거가 아니다. 기존 live E2E의 7일/SVG/요약 박스 선택자는 새 계약으로 갱신했지만 운영 실행은 하지 않았다. 이미지/앱 빌드는 별도 담당 범위다. 운영 속도나 p95 개선율을 주장하지 않는다.

원장은 Git 밖 `weather-transport-evilcharts-20261112/fuel30-qa`와 `fuel30-pg-qa`에 보존한다. 핵심 기록은 `frontend-results-r6.json`, `frontend-results-r7.json`, `backend-sqlite.log`, PG `results.json`, `browser/final-results.json`이다. 초기 SVG/7일 기대치 불일치, JSDOM Canvas/ResizeObserver 부재, Docker 임시 mountpoint 부재, 지연 import 중 기본 5초 시험 timeout, 별도 fork worker 시작 60초 timeout은 원 실패로 남긴다. 최종 DOM 단위 시험은 엔진 경계만 대역 처리하고, 별도 옵션 검증과 실제 브라우저 캔버스로 보완한다.

초기 로컬 브라우저 Chromium1254/C 경로 profile의 SIGTRAP 및 기존 Firefox 프로토콜 불일치도 원 실패로 보존했다. 기존 Chromium1248 실행파일(실제 156.0.8078.4)과 소유 /dev/shm 임시 profile로 정상 확인했다. DrvFS의 Windows 편집은 기본 Vite watcher가 놓칠 수 있어, 최종 로컬 fixture는 polling과 새 서버의 실제 파일로 확인했다. 소유 QA 서버·브라우저·테스트 DB는 종료하고 다른 작업자/서비스에는 신호를 보내지 않는다.

## 화면

아래는 합성 fixture 화면이다. 운영 가격이나 실제 주유소의 수치를 나타내지 않는다.

![모바일 유가 통계](assets/2026-11-13-fuel30-375.png)

![모바일 주유소 상세](assets/2026-11-13-fuel30-station-375.png)

![PC 유가 통계](assets/2026-11-13-fuel30-1440.png)

![PC 주유소 상세](assets/2026-11-13-fuel30-station-1440.png)

## 남은 한계

과거에 기록되지 않은 Top 10은 즉시 채우지 않는다. 공급자 가격 오류를 임의 보정하지 않는다. 운영 배포/실제 API 통합 수용·CI·독립 리뷰·main 머지는 이번 분담에서 실행하지 않으며 Root가 별도로 정산한다. 공항/항공편/고속도로/Weather/캐시 이전 요청은 다른 분담 범위이고 유가 기능으로 완료 처리하지 않는다.
