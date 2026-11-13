# 공항 주차 분석 날짜와 열린 화면 갱신 조사

## 운영 관측과 소스 문제의 구분

Root가 별도로 읽은 재배포 전 공개 API 원장에서는 운영 health가 이전 제품4998226이고 김포 현재 주차5개가 모두2026-11-03 08:08:03UTC 관측, 같은 날08:08:54~59UTC 수집이었다. 11월13일의 최근 Dagster 공항 실행은 부분 성공·관측19개였으므로 김포 수집 성공으로 해석할 수 없다. 이 조사 작업은 운영 API·제공기관을 다시 호출하거나 수집을 실행하지 않는다. 김포 원천 누락의 제공기관·설정·실배포 원인은 Root의 별도 실제 관측 범위이며 최신 운영 상태는 그 후속 원문을 우선한다.

최신 소스의 분석 페이지에는11월3일을 고정하는 날짜 선택기나 최대 날짜가 없다. 하루 흐름 날짜는 응답의 실제 `time_series.items[].bucket_at`으로 만든다. 과거 자료 조회 달력의 최대값도 최신 관측이 아닌 KST 오늘이다. 자료가 없는 날을 생성하거나 오래된 관측을 오늘 값으로 옮기지 않는다.

기본 분석 DB 캐시는 생성10분 제한과 scope의 새 `collected_at` 검사를 통과해야 재사용한다. 최신 소스의 기본 분석은 원본 관측 reader를 사용한다. 영구 통계의 모든 분석 읽기 전환·원본 정리는 여전히 별도 단계이며 이 변경은 archive/backfill/prune, 통계 재발행·보관 기간을 변경하지 않는다. 이 소스 사실을 이전 운영499의 실제 실행 증거로 소급하지 않는다.

## 재현한 독립 문제와 수정

`useAnalyticsData`는 선택이나 `dataVersion`이 바뀔 때만 조회했다. 열린 화면은 collector marker가 그대로인 동안 만료된 캐시의 재계산·지연 발행·일시적 실패 복구를 다시 읽지 않았다. 새 응답이 준비되어도 이전 성공이나 오류가 화면에 남는5개 반례를 원 소스에서 재현했다.

분석이 활성화되고 화면이 보일 때60초마다 저장된 분석을 다시 읽고 포커스·가시성 복귀에도 갱신한다. 분석과 최종 항공편 요청이 모두 끝나기 전에는 새 주기/복귀 요청을 시작하지 않아6초 안내 이후의 늦은 항공편을 중단하지 않는다. 선택 변경·비활성화·unmount 시 요청·타이머·리스너를 정리한다. 원30초 항공편 최종 상한·응답 폐기·범위 구분은 유지한다. `generated_at`이 오늘이어도 관측이11월3일이면 그 날짜와 실제0값을 그대로 표시한다.

## 숨은 탭의 차트 초기화

실제 AnalyticsView fixture는 처음 요일 탭을 보여주는 동안 `forceMount`된 하루 흐름 차트를 폭0으로 초기화해 ECharts 경고를 냈다. 이 경고를 무시하거나 타임아웃을 늘리지 않고, 하루 흐름 탭을 처음 방문할 때만 시각 엔진을 마운트하도록 보강했다. 자료를 기다리다 떠난 탭은 응답이 와도 숨은 상태로 처음 열지 않는다. 실제 표시한 뒤 떠날 때는 컴포넌트를 보존해 날짜 선택·키보드·24시간 축·다시 표시하는 상태와 resize를 유지한다.

정확한 source를 탐색하는 Tailwind fixture에서도 선택하지 않은 임계치 패널은 `data-state=inactive`, `hidden=false`, `display=grid`였다. 무계층 주차 CSS의 grid가 utilities 계층의 hidden을 덮는 실제 제품 경로였다. 각 `forceMount` 패널에 선택 상태와 일치하는 native `hidden`을 명시해 기존 보호 CSS를 적용했다. 스타일시트·공통 라이브러리를 바꾸지 않으며 비활성 콘텐츠의 키보드/접근성 경로도 함께 닫는다.

## 검증 원문과 진행 범위

원문은 Git 밖 `transport-reported-regressions-20261113/parking-refresh-*`, `parking-tab-visit-red-exact`, `parking-inactive-*`에 보존한다. 단계가 겹치는 시험은 합산하지 않는다.

- 원 소스의 새 갱신 반례5개는 모두FAIL, 선택하지 않은 기존17개는SKIP였다. 후속 옛 설치본의 hook22개·view7개는 통과했지만 Motion14.12.0이어서 최신 main14.13.0의 최종 수용으로 쓰지 않는다.
- 첫 Docker는 시험 실행 전 읽기 전용 config 옆에 bundle 임시파일을 쓰려다EROFS1이었다. 후속은 config 복사와 캐시 쓰기 위치만 `/tmp`로 분리하며 제품 파일의 read-only 경계를 유지한다.
- 첫 실제 Chromium fixture는 폭0 경고1로FAIL, browser1/server0이었다. 경고 필터링으로 통과시키지 않는다.
- 정확한 manifest/lock을 자기 전용 설치 경로에 복사했다. 첫 offline npm 설치는 정확 Motion tar3개가 npm 캐시에 없어ENOTCACHED1이었다. 원문을 보존하고 공식 lock integrity가 검산된 읽기 캐시3개만 자기 캐시에 보완했다. 후속 Node22.23.1/npm12.0.1 strict offline ci는0이며 모든 직접 의존성·lock bytes, Motion/framer-motion/motion-dom14.13.0·motion-utils14.7.0이 일치한다. 공유된 이전14.12 설치본·다른 작업자 설치본은 수정하지 않았다.
- 정확 환경에서 최초 방문 회귀1FAIL/7SKIP를 확인한 뒤 hook22+view9의 WSL31→Docker31·공개 타입·변경 lint·공통 의존성 guard·명시적 두 파일 Doctor를 통과했다. 수동 초점 이동의 시험 act 경고는 원문을 보존하고 올바른 act 경계로 보정했다. 새 native hidden 회귀1FAIL/9SKIP와 DOM 진단을 추가 확인한 뒤 표시 계층만 최종 view10 WSL→Docker로 검증했다. 같은 hook22·전체 시험을 재실행하지 않았다.
- 보조 RED runner의 `analytics_view_unchanged`는 해당 실행 동안 제품을 변경하지 않았다는 표지다. 최초 방문 RED는 main의 view, native hidden RED는 첫 방문 gating까지 적용한 중간 view였으며 둘을 같은 기준 소스로 표시하지 않는다.
- 최종 `parking-refresh-browser-final-r4`는 실제 Chromium156 PC1440/mobile375에서 초기 숨은 Canvas 미마운트, 비활성 panel 숨김, 같은 marker/dataVersion의60초 API 재조회, 오래된 응답의11월3일 유지와 이후 제공된11월13일 반영, 날짜 키보드 토글·탭 복귀 state·0~1440축·resize를 확인했다. 오류·경고·외부 요청·문서 가로 overflow0, browser/server각0이며 전후 캡처를 직접 검토했다. 앞선 R2는 부가 패널 스타일의 한계를 보존하고 R3의 추가 가시성 검사 실패와 DOM 원문도 남긴다. 테스트 CSS의 탐색 범위만 실제 source로 고정했고 경고나 assertion을 숨기지 않았다.
- 최종 표시 보정은 공개/시험 타입·변경 view/시험 lint·공통 의존성 guard·해당 view Doctor도 모두0이다. 원 hook/두 파일 Doctor0는 변하지 않은 범위의 선행 원장으로 보존한다. 환경·캐시·fixture 실패를 성공 수에 합산하지 않으며 반복한 view9/10과 hook22를 더해 새 전체 성공 수로 쓰지 않는다.
- 생산 빌드·이미지·배포·운영 DB·수집·캐시 warm·자료 위조·SDK 재설치는 없다. 이 수정은 아직 소스 후보이며 운영 최신화 수용과 별개다.60초는 클라이언트 재조회 주기이지 원천 수집·서버10분 캐시를 포함한 최대 반영 지연 보장이 아니다. 소유 자식 정산·파일 지문·전용 환경 증거는 Git 밖 최종 원장으로 연결한다.

## 후속 검토: 범위 변경과 숨은 실제 엔진의 크기

독립 검토는 첫 방문 여부가 공항/주차장 범위별이 아니라는 추가 반례를 확인했다. 일별 자료를 한 번 본 뒤 다른 탭에서 범위를 바꾸거나, 빈 일별 응답을 본 뒤 다른 탭에서60초 후 첫 관측을 받으면 숨은 탭에서 엔진을 처음 만들 수 있었다. 공항/주차장 변경2개·실제 Canvas 크기/cleanup3개는 원 후보에서 실패했고, 최초 빈 응답 반례는 시험의 fake timer 이벤트 타임아웃을 별도로 보존한 뒤 native 이벤트 경계를 바로잡아1FAIL/12SKIP로 재현했다. 타임아웃을 늘리거나 제품 실패와 시험 오류를 합산하지 않는다.

일별 방문 기억을 공항/주차장 scope별로 두고 관측이 있는 응답만 방문으로 기억한다. 실제0값은 `lot_observations > 0`이면 유효하다. 이 view 보호와 별도로 실제 `ParkingLineCanvas` 노드의 폭·높이를 `ResizeObserver`로 확인하고, 어느 한쪽이라도0이면 시각 엔진만 만들지 않는다. 탭의 부모 컴포넌트와 날짜·배율·관측 선택은 유지하며 다시 보이면 최신 옵션으로 엔진을 연다. 노드 교체 시 기존 크기/테마 observer를 해제하고 새 노드를 구독한다. 공통 EvilCharts 엔진·시간축·데이터·의존성은 바꾸지 않았다.

실제 Chromium RED fixture 첫 실행은 API fixture의 scope 전환 호출 수를2로 잘못 한정해 타임아웃이었다. 이를 실제3회 전환을 기다리도록 분리 정정한 RED R2에서는 PC/mobile scope와 mobile 빈 응답, PC/mobile history 총5/6조건에서 숨은 엔진의100×100 fallback 또는 폭0 경고가 나타났다. PC 빈 응답은 그 실행의 모듈 로딩 순서상 숨은 초기화가 관측되지 않았으므로6개 모두 재현됐다고 쓰지 않는다.

수정 후 실제 Chromium156의 scope/빈 응답/history 각 PC1440·mobile375 총6조건은 숨은 엔진0, 다시 표시한 엔진의 양수 폭·높이, 일별0~1440축·날짜/배율 선택, history 키보드로 선택한 실제0의 툴팁 보존을 확인했다. 오류·경고·외부 요청·문서 가로 overflow0, browser0/server0이며6캡처를 직접 검토했다. 일별 캡처는 선택 보존을 확인하려고 날짜 선을 끈 상태이며, 비어 있는 축을 새 주차 관측 성공 증거로 쓰지 않는다.

새 통합 WSL 첫25개 중23PASS/2FAIL은 추가 범위 시험이 남긴 선택 cookie가 원래 두 시험에 전파된 fixture 격리 문제였다. `localStorage.clear()`만으로는 제품의 cookie fallback이 남는다. 제품 동작·전역 setup·기존 assertion을 바꾸지 않고 해당 파일의 `beforeEach`에서 기존 선택 cookie만 만료시켰다. 원 실패는 `parking-visibility-p2-qa`에 보존하며 후속 결과와 합산하지 않는다. 선행 hook22와 기존31/10 검증은 겹친 범위로 그대로 남긴다.

후속 `parking-visibility-p2-qa-r2`의 정확 환경 WSL25개와 read-only·network-none Docker25개는 모두 통과했다. 범위는 view13·Canvas3·history9이며192.27/189.33초다. hook22의 제품/시험은 변경하지 않아 선행 정확 환경 원장을 유지하며 성공 수를 합산하지 않는다.

같은 후속에서 공개 앱/시험 타입, 변경 파일 lint, 공통 의존성 guard, 변경 view/Canvas 두 파일의 Doctor `--blocking warning`도 모두0이다. 생산 빌드나 운영 수집을 이 검사로 대체하지 않는다. 최종 파일 지문·실제 종료·소유 Docker 잔여0·fixture 포트 종료·실키 부재 검산은 Git 밖 `parking-visibility-p2-final-receipts.json`에 연결하며, 선행 `parking-refresh-final-receipts.json`은 덮어쓰지 않았다.

Root의 별도 운영 조사에서는 구 KAC HTTP80 연결 거절과 공식 신규 HTTPS 인증 제약을 확인했고, 사용자 활용 신청 후 신규 API의 정상25주차장 응답을 확인했다. 이는 별도 진단 원문이며 이 UI 작업의 수집·DB 적재·운영 최신화 성공은 아니다. SDK 주소/파싱 개선 및 정규 수집 복구는 Root의 후속 원장을 따른다. 이번 UI 검증은 공식 제공기관을 호출하지 않는 fixture 수용이다.
