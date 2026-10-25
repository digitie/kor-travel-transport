# 공항 주차장 관리자 통합 수용 기록

이 문서는 parking-radar 전체 화면의 관리자 이식, 주차 수집 뒤 분석 갱신, 항공편 공동운항 복구를
함께 인계하기 위한 기록이다. 2026-10-26 KST 정산 기준으로 SDK PR12와 Transport PR134·135·136은
머지됐다. 코드 정본은 main `1e50dbc93a86818285a9de22a983d9fb5aa7fb9d`이며, 운영 수용은 아래 인계 원장으로 구분한다.

## 소스·머지·운영 상태

| 변경 | 검증 대상 소스 | 머지 상태 | 아직 별도로 수용할 항목 |
| --- | --- | --- | --- |
| 제공기관 SDK 공동운항 식별 | `python-krairport-api` `d6a1285111883f6942ba2cedafd2efcdcbef037b` | [SDK PR12](https://github.com/digitie/python-krairport-api/pull/12) 머지. merge commit `fd523eff3e14e666182fefca41aa478e42d55d2e`의 ancestor이며 전체 tree 동일 | 최종 SDK를 소비하는 Transport의 운영 항공편·성공 마커 |
| 기존 공항 job→분석 캐시 복구 | Transport `0a91260a2e7699de36403f4a94f2822ccca5896f` | [PR134](https://github.com/digitie/kor-travel-transport/pull/134) 머지. main `f5f96efa010f3bb77c220b1da6aa33a5601d2381`과 전체 tree 동일 | 운영의 자연 5분 tick 뒤 원본/run/cache/API 시각과 값 |
| 관리자 전체 주차 뷰 | Transport `ccfaa64dc8dc41aeb46cf95b02f41a6117fae89f` | [PR135](https://github.com/digitie/kor-travel-transport/pull/135) 전체 필수 CI·두 독립 최종 코드 PASS 뒤 squash merge `213c048216d8313cf5ff7f3f7b5ca043f5d6cb53` | 아래 실제 UI의 미확정 경계와 통합 배포 후 재확인 |
| 최종 SDK 소비 | Transport `dd6b39a2ca238ad2c1bee868370ecc4648d7cd99` | [PR136](https://github.com/digitie/kor-travel-transport/pull/136) 필수 CI·두 독립 최종 코드 PASS 뒤 squash merge `1e50dbc93a86818285a9de22a983d9fb5aa7fb9d` | 실제 운영 API·하루 흐름 성공 마커 |

PR135·PR136의 정확 소스 CI는 backend/frontend/관리자 필수 job이 모두 성공했고 선택 `live-e2e`는 건너뛰었다.
PR136 머지는 예상 통합 tree `60c7a5213ee25a5d21a578271fc146f66eb8173b`와 전체 diff0이며,
PR135의 `213c048…`가 ancestor임을 대조했다. `live-e2e` 건너뜀을 실제 UI 완료로 계산하지 않는다.

머지와 운영 반영은 별개다. 운영 반영 여부는 아래 인계 원장과 해당 배포 기록을 따른다.

## 네 뷰와 분석 네 탭의 대조

정본은 공개 앱의 기존 `frontend/src`다. 관리자 `/parking`을 항공·여객선 메뉴에 추가하고 같은
뷰·훅·차트·계산 UI를 내부 `@kor-travel/parking-ui` 파일 패키지로 사용한다. iframe이나 외부 앱
링크로 대체하지 않는다. 공개 `/`, `/analytics`, `/history`, `/fees`도 유지한다. [S1]

| 화면 | 유지한 정보·상호작용 | 수용과 한계 |
| --- | --- | --- |
| 현황 | 잔여면·빠듯한 곳·여유 있는 곳의 지표 3개, 공항/활성 주차장, PC 표·모바일 카드, 수용 규모·관측 시각·공휴일 문장 | 선택 범위의 보유 관측이 없는 초기 로딩·실패·미관측은 `—`. 기존 관측은 갱신 중·실패에도 관측 시각과 로딩/오류 안내와 함께 유지하며, 실제 0면은 `0대`. 15분 이상 지난 관측은 지연으로 구분. 빈 공항 목록·초기 실패를 영구 로딩으로 남기지 않음 |
| 분석 — 요일 | 요일×24시간 히트맵, 미관측 칸, 최고/최저 혼잡 시간대 | 기존 집계 API와 선택 범위 유지. 최초 로딩을 빈 자료로 먼저 판정하지 않음 |
| 분석 — 공휴일 | 공휴일·토/일의 날짜별 24시간 히트맵, 이름·날짜·가로 이동 | 공휴일 보조 자료를 주차 원본이나 요금의 휴일 정책과 혼동하지 않음 |
| 분석 — 임계치 | 잔여 50대/10대 미만의 요일 대표 진입 시각·표본, 날짜별 진입 시각·잔여면, 진입/회복 이벤트 | 기존 임계치·표본·기간 계약 유지. 데이터 부족·조회 실패 구분 |
| 분석 — 일별 흐름 | 0~24시의 최근 7개 날짜별 선, 날짜 토글, 주말/공휴일, 출발/도착 독립 토글, 4배 시간축, 당일 비행편 hover/click·선택 해제·키보드 버튼 | 비행편은 이 하루 오버레이에만 표시. fixture의 성공 마커와 실제 운영의 오류 표시를 구분 |
| 과거조회 | 기본 최근 7일·10분·`future_hours=0`, 관측 버킷의 최소/평균/최대, KST 범위 달력, 최근 7일 복귀. 명시적 날짜 범위는 양 끝을 포함한 일수가 3일 이하이면10분·14일 이하이면30분·14일 초과이면60분 | 명시적 7일 범위는30분으로 조회. 미래·최초 관측 이전 제한, 누락 구간·단독 점, 주말/공휴일 배경, 최신 관측 스크롤, hover/touch·가로 이동·초점 유지. 비행편 없음 |
| 요금계산 | 활성 주차장·소형/대형·KST 입출차, 필수/역전 시각 검사, 계산 중 중복 제출 방지, 총액·일별 구분/시간/요금, 미지원·오류 | 전체 주차장 선택 시 첫 활성 주차장으로 계산하며 합산 요금으로 보이지 않게 함. 현재 휴일은 토/일 기준이고 공휴일·할인은 별도 계산하지 않음을 `i`에 명시 |

공통 선택·새로고침은 한 곳에 둔다. 공항/활성 주차장을 localStorage와 쿠키 대체 경로로 기억하며
탭 왕복에서 분석 하위 탭·차트 토글·기간·요금 입력을 보존한다. 방문한 탭만 마운트하고 숨은 분석/과거조회는
재조회하지 않는다. 현황 진입부터 모든 분석·항공편을 한꺼번에 요청하지 않는다. [S1]

화면이 보이는 동안 15초마다 관측/수집 시각 표지를 확인하고 변경 시 자료를 갱신한다. 공항 변경의 선택 조회를
배경 갱신이 무효화하지 않으며, 늦은 이전 선택·계산 응답이 현재 값을 덮지 않는다. 공항 변경 중 focus/poll,
연속 focus, 오류 뒤 재시도를 실제 React 회귀로 검증했다. [S1, S2]

## 재사용·연계·인증 경계

- 파일 패키지의 명시적 `files`/`exports`에는 조회 UI·훅·lib·주차 CSS만 포함한다. 관리자 기본 `npm ci`는
  `install-links=true`로 물리 복사하고 React/Base UI/달력 의존성을 관리자에서 해결한다.
  공개 frontend의 `node_modules` 없이 설치·타입·빌드를 검증했다. Docker의 루트 빌드 문맥에서도
  같은 소스와 `.npmrc`를 복사한다. [S1, S2]
- CSS는 `.parking-radar` 범위와 관리자 접두어로 제한하고 기존 관리자 navy 톤·공통 필터 배치를 사용한다.
  다른 지도/버튼/전역 테마를 덮지 않는다. 필요한 안내는 `i`로 제공한다. [S1]
- `/parking?airport=…&lot=…&view=…` 직접 진입과 `/flights` 왕복에서 공항/주차장을 전달한다.
  항공편·공항 지도는 기존 화면으로 연결한다. 그 지도 상세의 주소는 좌표가 있을 때 지도 동작에 연결되고
  전화는 기존 `tel:` 경로를 유지한다. 주차 통합 실제 QA에서 주소/전화·실기기 수용은 **미실행**이다.
  [S1, S3]
- 수집 안내는 `/collections`와 기존 `dagsterJobRunsUrl("airport_collection_job")`을 사용한다.
  정수 `CollectionRun.id`를 Dagster UUID로 만들지 않는다. 실제 실행 ID를 확인하지 못한 경우에는
  이 공항 job의 실행 목록까지만 연결한다. 링크 제공은 job 실행·스케줄 활성 확인과 다르다. [S1]
- 공유 `buildApiClient`의 기존 BFF 호출 방식을 재사용한다. 공개 앱의 기본 BFF base는 `/api/backend`,
  `versionPrefix`는 `/v1`이다. 관리자는 기존 BFF base `/api/transport`와 빈 `versionPrefix`를 소비한다.
  관리자 인증 GET 허용 목록에 추가한 경로는 `dashboard/bootstrap`, `dashboard/analytics`,
  `admin/collector-status`, `parking/analytics/timeseries` 네 개다. 기존 공항/현황/항공편 읽기를 재사용한다.
  POST는 `fees/calculate`만 허용하고 세션·동일 origin·JSON·선언/실제 본문 4KiB를 검사한다.
  내부 주소/비밀값을 브라우저에 노출하거나 수집/복원/일반 admin 쓰기를 열지 않는다. [S1]

## 기존 5분 job과 분석 캐시 복구

격리 DB의 기존 Dagster job에서 잔여 80면의 캐시를 만든 뒤 새 관측 5면을 저장해,
현재 API는 5면·시계열은 80면인 단절을 정상/부분 성공 양쪽에서 먼저 재현했다.
새 job을 만드는 대신 기존 `airport_collection_job`의 원본 commit 뒤 기본 분석 갱신을 연결했다. [S4]

- 정상 tick은 새 스냅샷이 0건인 중복 관측이어도 이전 파생 실패를 복구한다. 부분 성공의 저장분도 집계하고
  원래 Dagster 부분 실패를 유지한다. 캐시 실패는 별도 transaction만 rollback하며 원본/run을 되돌리지 않는다.
  원본 성공 뒤 파생 실패도 Dagster 실패로 구분하고 자동 재시도하지 않는다.
- 기존 airport advisory key의 재집계 잠금을 사용한다. 잠금 경합은 갱신 0건으로 건너뛰며 수집 실패로 바꾸지 않는다.
  빈 `TimeoutError` 등도 실패 여부와 표시 문자열을 분리해 원인 종류를 보존한다.
- 캐시 `generated_at`은 잠금 획득 뒤 첫 원본 조회 전의 보수적 watermark이며 `source_observed_at`과 다르다.
  같은 scope의 `collected_at > generated_at` 적재가 있으면 캐시를 거부한다. 뒤늦게 들어온 더 오래된 관측도
  최대 `observed_at`만 비교해 놓치지 않는다.
- 생성 후 10분 초과 또는 미래 시각의 캐시는 직접 계산으로 돌아간다. 유효한 빈 배열·캐시 부재/만료·원본 0건·
  중복 삽입 0건·수집 실패를 구별한다. DTO·기간 기본값·주차와 비행편 분리·기존 5분 일정은 유지한다.

운영의 자연 tick에서 최신 관측이 API까지 반영되는지는 아래 인계 항목으로 남긴다. [S4, S5]

## 항공편 SDK 복구와 실제 조회·재생의 구분

KAC의 서로 다른 정상 공동운항 편명이 같은 `fid`를 공유해 옛 SDK가 전체 조회를 중복으로 거부했다.
제공기관 필드/페이지 파싱은 형제 `python-krairport-api`에서 수정했고 Transport에는 우회 파서·wrapper·새 DTO를
추가하지 않는다. 방향별 `(fid, flight_id)`로 식별하며, 공유 `fid`는 명시적 공동운항·동일 대표 편명/노선/예정시각·
제공된 날짜/방향·요청 공항을 대조한다. 완전 중복·페이지 겹침·메타 변경·잘림·예산 상한 실패는 유지한다. [S6, S7]

| 검증 층 | 확인한 결과 | 확대해서 해석하지 않을 내용 |
| --- | --- | --- |
| 최초 SDK `0a7648450c62027fb95146a2442c3f925c80d6aa` 실제 조회 | 김포 2026-10-25, 재시도/redirect 0·1RPS·합산 상한 20페이지 중 GET 6회, 출발 235+도착 238=473편 | 최종 SDK의 새 외부 조회, 전국/다른 날짜 완전성, 같은 순간의 스냅샷 아님 |
| 최종 SDK `d6a1285…` 재생 | 보존된 원본 XML 6페이지/473행의 정규화 모델·raw 동일, 추가 GET 0 | 운영 API 또는 UI의 성공 항공편 수용 아님 |
| 소비자 `dd6b39a…` 기존 API 재생 | 기존 공동운항 묶음 계약으로 353마커·구성원 473편. 편명/방향/예정 UTC 다중집합 보존 | 353을 원본 편수 감소·누락으로 세거나 473과 합산하지 않음 |
| 공개 부분 fixture | SDK 100행, Transport 새 API 회귀용 7행 | 부분 집합의 시험용 총건수는 하루 전체 완결 증거 아님 |
| PR135 실제 운영 자료 UI | 옛 운영 SDK의 HTTP200·`upstream_error`·항공편 0을 오류로 표시, 허위 성공 마커 없음 | 최종 SDK 배포 뒤 성공 마커를 검증한 것으로 세지 않음 |

항공편 성공 마커는 새 소비자가 운영에 반영된 뒤 하루 흐름과 `/flights`에서 확인한다. [S3, S6, S7]

## 소스별 검증 원장

각 행은 다른 실행 또는 포함 관계다. 단위·집중·회귀·재생·실자료 UI를 더해 하나의 성공 합계를 만들지 않는다.

| 대상 | 확인한 결과 | 출처·제한 |
| --- | --- | --- |
| SDK 최종 `d6a1285…` | WSL 오프라인 304통과, live 3개 제외, coverage 92.55%; CI 8개 SUCCESS; 두 독립 최종 PASS | S6. live 제외를 실제 외부 실패/성공으로 바꾸지 않음 |
| 캐시 `0a91260…` | WSL 전체 1170통과/23건 건너뜀; backend CI 1191통과/2건 건너뜀; 격리 PG 집중 122통과; 두 독립 최종 코드 PASS | S4, S5. 집중 검증은 전체에 추가 합산하지 않음 |
| 캐시 격리 PG 전체 실행 | 정확한 실행 컨테이너의 독립 `docker wait` exit0 | S5. stdout 완료 표시는 919에서 끊겼고 pytest 최종 건수·wrapper `full.exit`는 회수 못함. CI의 1191/2를 이 실행의 건수로 복사하지 않음 |
| UI 최종 `ccfaa64…` | 작성자 WSL 공개142·관리자282/타입·lint·빌드, 통제 응답 UI34·개발2; 독립 Docker 관리자282+공개142/타입 PASS | S1, S2. 제품이 같은 `7d42d86`의 UI/빌드 증거와 시험/문서만 바뀐 최종 커밋의 동일성 확인 포함 |
| UI 최종 CI·독립 코드 리뷰 | 정확 `ccfaa64…` backend CI 1179통과/2건 건너뜀/6경고, 50분11초; frontend/관리자 SUCCESS. James/Popper 모두 최종 코드 PASS·확정 P0/P1/P2 및 코드 blocker 없음 | S8. James42+첫 열기4회·Popper4UI+BFF10의 사전 점검 수를 최종 성공 합계에 더하지 않음. Firefox1440 UNKNOWN은 별도 추적 |
| 최종 UI+운영 읽기 자료 | 전체 흐름 5개 환경 조합 PASS, Firefox1440 첫 열기 1개 UNKNOWN; 320px/100·200%×3환경의 geometry 6개 PASS; PNG56·pageerror0·금지 write0 | S3. 뒤늦은 재시도·fixture·다른 환경을 합쳐 6/6 PASS로 만들지 않음 |
| 소비자 `dd6b39a…` 집중·재생 | 새 API9+기존 항공편 포함 집중21 PASS; 최종 SDK473행 재생/API353마커 보존 PASS | S7. 아래 전체 검증과 합산하지 않음 |
| 소비자 WSL 전체 | 1168통과/22건 건너뜀, 3645.54초, exit0 | S7. 실제 종료·최종 summary 회수 |
| 소비자 PG 전체 | 1182통과/2실패/6건 건너뜀, 3102.83초, exit1. 독립 container wait도1 | S7. 전체 PG 성공 아님. 실패 원인과 집중 재검증은 다음 절 참조 |
| 소비자 동일 실패2개 집중 | 소스·SDK·106의존성·assertion/rewrite를 유지하고 `PYTHONPYCACHEPREFIX`만 격리해 2통과/0.45초/exit0 | S7. 환경 원인 분리이며 전체 PG 결과를 바꾸지 않음 |
| 소비자 CI·독립 코드 리뷰 | 정확 `dd6b39a…`의 PR/push CI 필수 job SUCCESS, 선택 live 건너뜀. James/Popper 최종 코드 PASS·잔여 확정 P0/P1/P2 및 blocker 없음 | S7. 두 리뷰 모두 원래 PG 실패와 최소 환경 격리 수용을 독립 확인 |
| 캐시+소비자 합성 tree `d247074e1480afc240c344e5fdf4cc16e914f5ec` | 새 PG에서 캐시12+소비자9=21 PASS/exit0, migration/check PASS. SDK25파일(`.py`24개+`py.typed`1개)·106의존성 버전·나머지 VCS mismatch0 | S9. 최종 관리자까지 포함한 운영 배포 수용이나 전체 회귀 아님 |

캐시 전체 PG 검증 환경은 소유 label을 확인한 임시 PG만 종료했다는 조율 인계를 받았다.
소스·로그·Node 의존성은 보존하며 다른 프로젝트의 프로세스·DB 정리로 범위를 넓히지 않았다.
미회수된 pytest 최종 출력은 위 원장의 제한으로 유지한다. [S5]

### 소비자 PG 실패와 검증 환경 분리

소비자 PG 전체의 두 실패는 기존 `test_transport_collection.py` 오류 위치 문자열의 assertion이다.
WSL과 Docker가 공유한 pytest `.pyc`의 `co_filename`에 WSL `/var/tmp/…` 절대 경로가 남아,
Docker `/repo` 기준 formatter가 `tests/test_transport_collection.py:…` 대신 basename으로 표시했다.
원래 전체 traceback·summary·exit1과 bytecode 경로/소스 해시 검사를 보존했다. [S7]

소스·SDK·106개 의존성·원래 assertion과 pytest rewrite를 유지하고 `PYTHONPYCACHEPREFIX`만 격리한
동일 두 사례는 2통과/0.45초/exit0이었다. assertion 완화나 formatter 수정 없이 환경 원인을 분리한 결과이며,
원래 PG 전체 1182/2실패/6건 건너뜀을 전체 성공으로 승격하지 않는다. James는 `.pyc`를 실행하지 않고 파싱한 경로와
정본 formatter로 실패 문자열을 재현했고, Popper는 소스 해시·의존성 대조로 같은 원인을 확인했다. [S7]

이번 소비자 전체 실행은 최종 summary와 wrapper/독립 container exit를 모두 회수했다.
이는 캐시 PR134의 stdout/최종 건수 미회수와 다른 실행이다. 검증 종료 뒤 소유 PG만 정리했고 잔여 컨테이너는0이며,
원본·로그·소스·Node 의존성은 보존했다. [S7]

### 실제 UI의 미확정·지원 한계

실자료 전체 흐름은 n150 Native Chromium과 WSL Chromium의 375×812 coarse/1440×900,
WSL Firefox 375×812 coarse에서 통과했다. WSL Firefox 1440×900은 첫 달력 opening 중
20~20만 요청되고 두 번째 날짜는 focus만 된 단발 현상으로 전체 흐름을 완료하지 못했다.
350ms 안정화 후 성공, sleep 없는 event trace의 미재현, 별도 fixture 첫 열기 4회를 이 최초 결과의
해소로 합산하지 않는다. 원인·제품 심각도 미확정으로 추적한다. [S3, S8]

320px geometry는 날짜·월 이동 44px, 일곱 요일·모든 날짜, Portal 상하좌우·겹침·가로 넘침·Escape 초점을
대조했다. 이것은 자동화 브라우저의 coarse 환경이며 실제 Android/iOS 기기 수용은 아니다. [S3]

최종 리뷰가 끝난 뒤 조율 담당자가 검증용 controller·preview·forward 5개 PID의 CWD/starttime/명령 소유권을
확인하고 모두 종료했다. `parkingccf-final-cleanup.json`의 소유/종료 결과를 대조했으며 로그·원본·스크린샷은
보존돼 있다. 실제 UI 원본 요약의 ‘리뷰용 미리보기 유지’는 당시 상태로, 현재 실행 중이라는 뜻이 아니다. [S3]

ICN 주차장35·소형·90분의 3600원은 저장된 generic 룰과 실제 API/UI/일별 내역이 일치한다는 증거다.
현재 공식 요금의 정확성을 입증하지 않으며 공휴일·할인·모든 주차장/차종 지원으로 넓히지 않는다. [S3]

GMP 선택 주차장 분석의 실제 표본은 약2.5~4.4초로 1초 목표를 충족하지 못했다. 옛 SDK/캐시를 사용하는
운영 자료를 읽은 UI 검증이며 새 캐시 릴리스·자연 tick 이후의 지연 수용은 아니다. 격리 PG 표본의 직접 계산
fallback도 약2초였으므로, 캐시 miss를 오래된 값으로 숨겨 성능을 좋게 보이게 하지 않는다. [S3, S4]

## 빌드·운영 검증 담당 인계

운영 호스트·NVMe·daemon·Transport instigator는 현재 배포 런북과 ADR-014를 따른다.
배포 기록에서 아래 항목의 결과와 증거를 연결한다.

| 확인할 것 | 남길 증거·판정 | 현재 |
| --- | --- | --- |
| 통합 소스 | main `1e50dbc…`의 캐시·관리자·SDK pin과 검증된 merge/tree를 대조. 빌드 후보에서도 파일 패키지·lock/vendor·설치 소스를 대조 | 코드 정산 완료·빌드 후보 대조 인계 |
| 자연 5분 수집 | 같은 공항/주차장의 실제 Dagster run UUID·시작/종료/결과, 원본 관측/적재·건수, 다음 자연 tick의 기록. 중복 삽입0도 정상 여부 구분 | 미수용 |
| 원본→캐시→API | 원본 `observed_at`/`collected_at`, cache `generated_at`/`source_observed_at`, 선택 scope·API 값·응답 생성 시각을 한 실행 창에서 대조 | 미수용 |
| 파생 실패·지연 | 원본 성공과 파생 실패의 상태 구분, 지연 적재/만료 시 직접 계산, 캐시 복구 뒤 동일 관측. 운영에 실패를 주입하지 않고 관측/격리 검증을 구분 | 코드 검증 완료·운영 대조 대기 |
| 항공편 성공 | 최종 SDK를 소비하는 실제 `/flights/status`와 `/flights`, 하루 흐름 마커의 방향/시각/대표·개별 편명. 주차 7일 시계열에는 마커 없음 | 재생만 확인·실제 성공 마커 대기 |
| 모바일·달력·연계 | 미확정 Firefox 첫 opening 판정, 실제 기기의 지도/주소·전화·초점·탭 보존, `/parking`↔`/flights` 범위, 정확한 Dagster job 링크 | 일부 자동화 수용·미확정/실기기 대기 |
| 성능 | 같은 배포 SHA/자료 범위에서 current/bootstrap/analytics 응답과 cache hit/miss·화면 표시 지연. 단일 표본을 p95로 쓰지 않음 | 목표 미달 표본 있음 |
| 요금 지원 | 실제 저장 룰의 공항/활성 주차장/차종·유효 기준, 공식 현재 요금과의 별도 대조, 미지원·할인/공휴일 안내 | 저장 룰/API/UI 일부 일치·공식 정책 수용 대기 |

## 정합 점검

- 소스 SHA·merge SHA·ancestor/tree, PR 상태, 실제 UI 요약의 5 PASS/1 UNKNOWN·6geometry·56PNG,
  SDK 235+238=473·API353마커의 포함 관계를 원장과 대조했다. 실자료와 재생의 추가 GET을 분리했다.
- 캐시 PG의 독립 exit0와 미회수 최종 건수를 분리했다. 919는 회수된 완료 표시의 수이며 통과/전체 건수로 쓰지 않는다.
  출력 미회수의 원인은 확정하지 않았다. 같은 다음 노드의 다른 실행 통과를 해당 실행의 최종 summary로 만들지 않는다.
- UI의 `7d42d86` 실제60ms 주기 시험 실패는 제외하지 않고 원본과 보존한다. 제어된90ms 정체로 같은 실패를 재현한 뒤
  해당 시험만 기본15초×2의 가상 시계/act/정리로 보완했다. 최종 `ccfaa64…`의 Docker142와 이전 141/1을 분리했다. [S1, S2]
- `HistoryView.pickIntervalMinutes`는 명시적 범위의 포함 일수에 따라 3일 이하10분·14일 이하30분·그 이상60분을 선택한다.
  기본 최근7일은 날짜 범위 없이 `days=7`로 요청해10분을 사용하며, 명시적7일 범위30분도 기존 동작이다. [S1]
- 1차 점검은 네 뷰/분석 네 탭·공유 소스/API 경계와 각 검증의 출처·포함 관계를 대조했다.
  2차 점검은 최종 merge/tree·SDK pin, PG 원본 실패/집중 수용, 개별 보고서·상태·색인의 숫자와 링크를 대조했다.
  지도 현재 상태도 Common46·Weather170·Transport132의 최종 코드 머지와 다른 소비자/운영 후속으로 정정했다.

T-PARK-01/02의 운영 시각 대조·수집/분석 수용, C-MAP-01/T-MAP-01의 전체 소비자·실기기,
유가 이력/선호/통계와 일반·도시철도 실제 시간표 등 기존 backlog는 이 문서나 주차 UI 이식으로 완료하지 않는다.
공항 주차 예측에 필요한 충분한 과거 표본·주차 가능성 보장도 새로 확보했다고 쓰지 않는다.

## 출처 원장

원시 로그를 직접 대조한 결과와 검증 조율 담당자가 전달한 최종 판정을 구분한다.

| 표기 | 정본·확인 위치 |
| --- | --- |
| S1 | [PR135 정확 소스의 개별 보고서](https://github.com/digitie/kor-travel-transport/blob/ccfaa64dc8dc41aeb46cf95b02f41a6117fae89f/docs/reports/2026-10-25-admin-airport-parking.md), 같은 커밋의 `airport-parking.tsx`·`flight-journey.tsx`·`journey-controls.tsx`·`dagster-scope.ts`와 공유 `frontend/src` |
| S2 | 작성자 `/home/digitie/dev/admin-parking-standalone-20261025/evidence/review-final/parking-ui.json`·`review-dev/parking-ui.json`; 독립 최종 `/var/tmp/codex-parking-admin-qa.yoC1fA/{source-sha.txt,verification.log}`; 주기 재현 `/var/tmp/codex-parking-timer-qa-20261025/evidence/` |
| S3 | `/var/tmp/codex-live-ui-20261025/parking135-ccf-actual-final-summary.json`과 그 증거 목록의 원본 JSONL/PNG/소스 지문. 요약의 screenshot 배열56개·환경6개 중5PASS/1UNKNOWN·geometry6개를 직접 대조. 종료 정본은 같은 폴더 `parkingccf-final-cleanup.json` |
| S4 | [캐시 복구 보고서](2026-10-25-parking-analytics-refresh.md), 정확 소스 `0a91260…`/main `f5f96ef…`, `/var/tmp/codex-parking-analytics-final.94LKtZ/wsl-full.log`; 초기 집중/PG/격리 성능 경로는 개별 보고서 참조 |
| S5 | `/var/tmp/codex-parking-analytics-final.94LKtZ/pg-tools-final/readonly-diagnosis-20261025.json`. 정확 컨테이너·명령·독립 wait exit0·source211파일 mismatch0·미회수 항목을 구분. PR134의 최종 CI와 두 리뷰 판정은 검증 조율 인계(2026-10-25) 및 PR 정본 |
| S6 | [SDK 최종 공동운항 계약](https://github.com/digitie/python-krairport-api/blob/d6a1285111883f6942ba2cedafd2efcdcbef037b/docs/kac-flight-gateway.md), [SDK PR12](https://github.com/digitie/python-krairport-api/pull/12)의 최종 검증/리뷰·CI. 로컬 Git에서 ancestor와 동일 tree를 읽기 대조 |
| S7 | [항공편 복구 보고서](2026-10-25-parking-flight-codeshare.md), [PR136](https://github.com/digitie/kor-travel-transport/pull/136), [정확 소스 CI40193943819](https://github.com/digitie/kor-travel-transport/actions/runs/40193943819)·push40193940472. `/var/tmp/codex-flight-consumer-final-v2.kUWMro/verification-final.json`과 `{wsl,pg}/full.log`, `pg/{pycache-path-inspection.json,path-isolated-focused.log,path-isolated-focused.exit,independent-container.exit}`를 직접 대조. 최종 James/Popper 판정·merge/tree는 검증 조율 담당자의 2026-10-26 인계 |
| S8 | 검증 조율 담당의 2026-10-25 최종 인계: PR135 정확 `ccfaa64…`의 James/Popper 최종 코드 PASS·미확정 실제 경계 추적·머지. [정확 소스 CI40192234387](https://github.com/digitie/kor-travel-transport/actions/runs/40192234387)의 head/conclusion 및 backend job `121165492154`의 1179/2/6경고·실행시간을 직접 대조. push40192231244도 필수 SUCCESS라는 인계 포함 |
| S9 | `/var/tmp/codex-cache-flight-integration-v2.484dm1/{source-tree.txt,pg/focused.log,pg/focused.exit,pg/migrate.log,pg/alembic-check.log}`. 21PASS/exit0와 SDK25파일(`.py`24개+`py.typed`1개)/106버전·나머지 VCS 불일치0을 직접 대조 |

James/Popper 판정은 정확 소스 SHA·최종 결과·PR/CI와 조율 담당자의 전달 근거로 기록한다.
