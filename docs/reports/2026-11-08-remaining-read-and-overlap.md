# 남은 조회 지연과 대표 카드 겹침

## 2026-11-08 — 남은 조회 지연·대표 카드 겹침 수정

대표 카드의 원 좌표·전5유종을 보존하며 화면상 충돌을 분리했다. 공간 부족 시 지도 내부의 한정된 스크롤 목록으로 모든 대표를 읽고 선택한다. 원점 연결·키보드 접근을 보존하며 WSL/Docker37개씩·타입/린트·실제저장DTO15지역 Firefox fixture를 검산했다. 아직 새 UI 이미지 배포 전이다.

실제 새 이미지·Manager/일정·HTTP·n150 PC/모바일 결과는 배포 뒤 별도로 정산한다. 기존 실패와 속도 목표 미달은 유지한다. 원장 weather-transport-remains-20261108/plan.json, UI 원문 fuel-region-overlap-20261108/manifest.json. 새 리뷰/SDK설치/백업복원 게이트는 추가하지 않는다.

## 첫 실제 반영과 후속 실패 재현

첫 최소3이미지(Weather API48e81c38·web86ebc25b, Transport UIff4aaecd)는 정상G/R에서 실제 반영했다. 첫 Invocation6237ef93은 done/Main0/cgroup부재,70개 소유 자식 종료0, Manager 양 앱 healthy·원27/20 일정·환경4파일/CS·다른 역할 보존이다. 이 배포 성공과 아래 수용 실패를 구분한다.

실제 HTTP 첫 current는13.394초503/statement_timeout이었다. 최소62초 뒤 current33.180초200, daily18.394초200/조건부7.852초304/만료 뒤14.508초200이며 원천 stale는 그대로다. 재시도/수동 수집/SQL 제한 확대는 없다. n150 R2는 Transport 카드 픽셀 겹침0·전5유종/목록 일치지만 일부 중심 클릭 가림, Weather PC 통과/모바일 마지막 복합 assert 실패다. 모바일 별도 좁은 관측은 문서375px/viewport375px·pageerror0이므로25열 상세표에 추측 clip을 추가하지 않는다. 첫 관측 보조의 os import 누락/원 실패·R2·정상 logout/브라우저 종료·비공개 자격 삭제 증거를 보존한다.

추가 native 실행에서 승인 상태 복합 CTE 도중 SQLSTATE57014/20.495초 중단을 재현했다. 이를 같은 RR의 소유·시도·공개 세대·서로 다른 run 키 집합4조회로 분리했다. 원본 owner_epochs JSON의 Python32자 비교·시도/세대/run 유실·실패 판정은 유지한다. current의 두3,305개 IN(약101/112KB SQL)과 daily 소유자 목록은 PostgreSQL 배열1개로 바꾸며 다른 dialect는 기존 IN을 유지한다. 실패 로그에는 자체 파일명·함수·행만 보태고 메시지/SQL/DSN/파라미터는 쓰지 않는다.

후속 WSL/Docker PG18은 각각86개 통과했다. 먼저 실행한70개/85개와 겹침은 합산하지 않는다. run 조회 대상 계수 시험의 원1실패는 보존하고 관련 대상만 세도록 고쳤다. NULL run·epoch 형식·유실/실패·캐시 만료·개별 예산·cursor/ETag/API도 대조했다. 후속 native 후보는34.286초에 같은 current100행 응답 생성을 완료했으나 이는 운영HTTP/p95나 코드 단독 개선율이 아니다.

Transport 실제 차단 노드는 투명한 kt-map-stage-summary 전체 폭이었다. 기존 SDK marker host는 이미 pointer-events:none이므로 그 가설의1줄은 버렸다. summary wrapper의 빈 영역 입력을 통과시키고 실제 내용은 입력 가능하게 유지한다. 두 앱은 화면 용량 초과 목록의 자동 열기를 data/viewport effect당 최초1회로 제한해 명시 접기가 유지되게 한다. 원 좌표·원점 연결·전체 값/5유종/키보드·미제공·특보는 보존한다. 이 후속 소스는 아직 새 이미지 반영 전이며 다음 실제 원장으로 정산한다.

## 후속 실제 배포·최종 화면 수용

후속 Transport UI6bd594e6를 반영했으며 기존 a886 API/CS는 그대로다. 첫 실제 배포·후속3역할·두 차례 Weather web 전용 build/배포의 첫 Invocation 모두 done/Main0/cgroup부재·모든 자식 종료0이다. 정상G/R·Manager 양 앱 healthy·원Weather27/Transport20 상태·보호 환경4파일·CS/DB/공용daemon/다른 역할·Cmd12201/12205/12305를 보존했다. migration/수집 취소/백업복원은 없다.

- 1440px: 대표15개/지도 배치15개, 실제 카드 교차0·접은 뒤 중심 입력 모두 가능·목록 전체값 일치·마지막 항목 자연 클릭, logout303
- 375px: 대표12개/지도 배치5개, 실제 카드 교차0·접은 뒤 중심 입력 모두 가능·목록 전체값 일치·마지막 항목 자연 클릭, logout303

n150 Firefox157 PC1440/모바일375의 실제 타일/지도와 모든 카드 값, 공간 부족 시 한정 스크롤 목록 및 명시 접기, 오류/가로 넘침0을 확인했다. Transport 요약 유종 컨트롤의 실제 클릭도 확인했다. Weather 현재/내일/부가 정보·시간별 예보표와 원천 미제공은 그대로다. 캡처를 실제 열어 검토했고 소유 브라우저 자식 종료·자격 파일 삭제를 확인했다. 이전 R2의 복합 모바일 assert는 좁은 별도 흐름에서 재현되지 않았으므로 원인을 해결했다고 소급 주장하지 않고 원문을 보존한다.

후속3역할의 Weather 모바일 목록 접기 뒤 pill1개 입력 가림은 실제 FAIL로 보존했다. 형제 access section의 ResizeObserver 관찰을 추가해 버튼 높이가 바뀔 때 재배치하고, 마지막 Weather 웹 전용 이미지에서 PC/모바일을 다시 수용했다. 이어 실제 PC/모바일 전환에서 빈 마커 자식의 offsetWidth/null 오류를 재현했고 유효한 host/button 쌍만 같은 배치에 사용하도록 수정했다. 원 회귀1FAIL과 후속 WSL/Docker35개씩·실제 effect Firefox 검산, 두 차례 원 브라우저 오류 관측을 보존한다. 최종 웹에서 같은 PC/모바일 전환·상세를 오류0으로 다시 수용했다. 원 API·CS·Transport는 두 웹 전용 교체에서 유지했다.

순차 소유 관측 표본이며 cold/p95·부하 통제·코드 단독 개선율이 아니다.
전체1초 목표와 원천 stale/미제공은 별도 한계다.

정본 weather-transport-remains-20261108/final-acceptance.json SHA 04a0622ca18995913794218d73ed0591040c532e1978fe8bd6a46ddb71502786. 후속 UI 원장은 fuel-region-overlap-20261108/followup-manifest.json(SHA719109ff224922c37ae6c8ad85aef6fdf789b87ba945dd75d6863d9fb994cdfb)이다. WSL/Docker backend86개씩, Transport UI33개씩·Weather 최종 UI35개씩·타입/린트0이며 겹친 시험은 합산하지 않는다. 문서 HEAD로 제품을 재빌드하거나 DraftPR174/208을 main에 머지하지 않는다.

Weather 저배율 캡처의 지역 카드 온도·상태는 정보 없음이었다. 이번 수용은 배치·입력·전환과 선택 서울 상세의 렌더링에 한정하며, 전국 지역 대표 기온의 완비나 초기 요청 대기와 원천 미제공의 구분을 증명하지 않는다. 선택 서울은 현재5.3도·내일4/12도·시간별 머리칸25개를 실제 확인했다.
