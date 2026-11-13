# 유가 통계 신고 증상 정산

## 재현과 원인 구분

기준 소스는 main `d9d4559c02076975c80b688410591da0106b5873`이다. 부모가 보존한
Git 밖 최초 읽기 전용 관측 stdout에서 실제 API health는 이전
`499822601abca3f050aa0cfe0e27fb446d22281d`였다. ALL은 HTTP200이지만 items/history0이고,
B027은10,205곳의 현재 집계가 있으나 유종별 product_code·ranking_complete·Top10 배열과
일별 history의 minimum/maximum 필드가 없었다. 최신 소스는 이미 ALL·30일·일별 극값을
지원하므로 이 차이는 운영 버전과 구 API 계약 문제다. 이 작업자의 운영 배포·외부 조회는0이며
부모의 공식 재배포 수용과 별도로 정산한다.

ALL의 빈 응답만으로 구 버전이라고 단정하거나5개 요청으로 숨기지 않는다. 화면의 정상 빈 결과는
선택한 범위의 전체 유종 통계가 없다고 표시하고 단일 ALL 요청 계약을 유지한다. 그래프에는
평균선과 최저·최고 세로선의 뜻을 표시하며 과거 극값이 없으면 미제공으로 남긴다. 엔진이나
가격/시간 값을 바꾸지 않는다. 페이지 설명의 남아 있던7일을 실제 조회 계약인30일로 맞췄다.

## 구 현재 세대의 Top10 보완

- 별도 RED는 동일 공개 세대에12곳×2유종의 완전한 point가 있고도 구 metrics_json에 순위가
  없다는 이유로 ranking_complete=False인1FAIL이다. 원문은 Git 밖 `fuel-qa/red/sqlite.log`다.
- 현재 선택 범위가 전국 전체 또는 고속도로 전체일 때만 저장된 동일 세대 point로 순위를
  응답에 보완한다. 현재 state·daily·point를 같은 SQL snapshot으로 읽고 최초 daily의 전체
  metrics와 개수·평균·최저·최고를 검산한 뒤 가격/문자열 station_key 순서의 최대10곳을 반환한다.
- 그 사이 공개 세대/집계가 달라졌거나 point가 일부 없으면 완전한 순위라고 하지 않는다.
  당시 동결된 point의 가격·주소·좌표를 쓰고 최신 가격이나 이후 기준정보로 대체하지 않는다.
  과거 daily·지역 세대·원본·state·JSON을 수정하거나 수집/publisher를 호출하지 않는다.
- 지역/노선의 과거 membership은 point에 없으므로 현재 주유소 주소·시군구로 추정하지 않는다.
  새로 발행되는 집계의 저장 Top10은 계속 사용하며, 보완 근거가 없는 구 지역 집계는 알려진
  최저가 한 곳과 미제공 사유를 보존한다. 이 한계를 새 지역 순위를 복원한 성공으로 바꾸지 않는다.
- 스키마·migration·OpenAPI·캐시 TTL·잠금·수집 정책·외부 재수집 변경은 없다. 기존 새 집계에
  ranking_complete가 있으면 추가 순위 SQL도 실행하지 않는다.

## 필터와 실제 화면

기존 DOM은 새로고침이 추이 범주 앞에 있고 PC의 label이 불필요하게 전체 너비로 늘어났다.
범위·유종·추이 범주를 PC의 작은 한 줄로 모으고 새로고침을 마지막 DOM/맨 오른쪽에 둔다.
좁은 실제 container나 모바일에서는2열로 바꾸며 터치 제어는 최소44px, 큰 글씨에는 자연
높이를 쓴다. 상세 아이콘·공용 지도 제어·다른 도메인 CSS는 바꾸지 않는다.

실제 Chromium156 fixture에서1440/1024/375와320·글씨200%의 before/after를 검산했다.
PC 필터 높이는66.09→36px이며 새로고침은 마지막 DOM/오른쪽으로 정렬됐다. 모바일은2열이고
모든 조건에서 문서 overflow0이다. 실제 ECharts의5유종×30일 custom range 각각에3개 선
도형이 존재하고 평균/최저/최고·KST 날짜·수집 시각을 마우스/터치 tooltip으로 확인했다.
Top10 표는 유종별10행이다. 이 fixture는 동일한 합성100곳 모집단과 일별 시각을 사용한
React/CSS/실제 캔버스 검증이며 운영 데이터나 제공기관 응답 증거가 아니다.

최종 원장은 Git 밖 `fuel-qa/browser-final/{results-before,results-after,parent-receipt}.json`과
`fuel-filters-{before,after}-{1440,1024,375,320}-{100,200}.png`다. 각 단계의 실제 생성 파일명은
원장에 대응하며 모든 조합을 뜻하지 않는다. PC/모바일/큰 글씨 캡처를 직접 검토했다.

독립 검토에서 글씨200% PC의620px 고정 container 경계가 필터 최소폭을 수용하지 못함을
추가 확인했다. 경계를38.75rem으로 바꿔 글씨 배율과 함께2열로 전환한다. 별도
`fuel-qa/browser-font-review`에서1440/1024·글씨200% 두 조건을 실제 재현하고 수정 후
overflow0·오른쪽 새로고침·마우스 극값·유종별10행을 확인했다. 원 before/after 캡처를
직접 검토했으며 앞선4조건의 통과를 이 새 경계에 소급하지 않는다.

## 시험과 환경 실패 보존

- backend는 신규3개와 기존7개, 총10개를 WSL SQLite/PG18·Docker PG18에서 각각 통과했다.
  최신 원천 가격/주소 변경과 미공개 point가 있어도 동결된 현재 순위만 사용하고, 지역 추정 금지·
  point 누락 시 보수적 반환·JSON 불변을 확인했다. `fuel-qa/green/focused-receipt.json`에 소유
  PG full CID/label 검산·제거·잔여0과 실제 부모 종료를 보존한다.
- admin은 WSL의 통계31개/차트1개=32PASS, network:none Docker의 같은32개와 순수 모델2개로
  34PASS다. 선행 실패 때 실행된 모델2개를 합산하지 않는다. typegen/tsc·변경 파일 lint·Common
  dependency guard도0이다. `fuel-qa/front-r3/{results,terminal}.json`이 정본이다.
- main의 Motion14.13.0과 구 설치14.12.0 차이를 먼저 발견했다. 정확한 lock integrity의
  Motion/framer-motion/motion-dom과 전이 버전을 자체 복사본에 맞췄고 다른 작업자의 설치는
  수정하지 않았다. parking-ui43파일도 공식 npm pack의 현재 source bytes와 대조했다.
- 원 WSL jsdom2파일은 본문 실행 전 worker 시작 timeout이고 순수 모델2개만 통과했다.
  RAM TMPDIR만으로 반복한 실패도 보존한다. 순수 jsdom 초기화가 C 경로85~116초였고 기존
  시험 이미지의 검증된 의존성을 자체 RAM cache로 재사용한 뒤0.985초였다. JS는 cache에서,
  native binding은 원래 검증된 실행 가능 파일에서 읽으며 패키지/시험 기대/timeout을 바꾸지 않았다.
- 실제 브라우저의 첫 C 임시 profile SIGTRAP, 후속 ready timeout/Next 전역 process 미제공,
  큰 글씨에서 화면 밖 차트를 스크롤하지 않은 포인터 실패를 각각 별도 원문으로 남겼다.
  최종 fixture는 Next의 기본 process.env 모양을 명시하고 차트를 화면으로 스크롤한 뒤 동일한
  포인터 값을 확인한다. fetch만 합성 DTO 경계로 고정하며 ResizeObserver·캔버스·포인터는
  실제 브라우저 기능이다. 제품 코드·시험 기대·timeout을 바꾸지 않고 이전 성공·실패·미시도를
  합산하지 않는다.

전체 pytest·생산/이미지 빌드·운영 배포·운영 DB 쓰기·원본 정리·수동 수집은 이 분담에서0이다.
부모의 다른 분담 변경은 보존하고 이 작업자의 commit은 통합 전 보류한다. 최종 CI·두 독립
리뷰·머지·실제 운영 버전/기능 수용은 부모가 별도로 확인한다.
