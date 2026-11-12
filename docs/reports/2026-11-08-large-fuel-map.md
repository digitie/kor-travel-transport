# 대량 유가 지도 조회 비용 개선

## 문제와 반영 범위

추가22d53 이미지의 실제5,000곳 지도는7.36MB·16.22/20.86초였다. 사용자 ‘대량지도 속도개선 진행’ 지시에 따라 같은 전체 DTO와 최신 양수 유종/출처/범위 필터를 유지하면서 PG 조회·구성·검증·직렬화 경로를 줄인다. 아직 이번 제품의 운영 배포는 완료 전이다. 현재 단일 Weather 배포 Root b6a5가 기존 수집의 자연 종료를 기다리며 G를 보유하고 있으므로 운영 Root/빌드를 겹치지 않는다.

## 구현

단일 유가 지도 요청의 PostgreSQL 경로는 선택한 주유소를 먼저 제한한 MATERIALIZED CTE와 최신 가격의 집합 JSON 투영을 사용한다. 수천 station/price Python 행·dict·datetime 객체를 반복 구성하지 않는다. JSON 날짜는 UTC로 정규화하되6자리 microsecond를 유지하고 NULL은 그대로 둔다. 유종은 C collation으로 Python 코드 순서와 맞추며 B027가 존재하면 값이NULL이어도 기존 선택 규칙을 보존한다. 여러 종류 지도와 SQLite는 기존 경로를 유지한다. 원본 JSON·외부 provider를 조회하지 않고 schema/index·SDK/의존성·웹은 바꾸지 않는다.

DB JSON은 같은 전체 TransportPlaceMapItem DTO로 검증하고 직렬화한 결과만 재사용한다. SHA256와길이뿐 아니라 입력 원문 바이트도 같아야 hit이다. 매 요청 실제 DB JSON을 다시 조회하므로 TTL/가격 반영 지연을 추가하지 않는다. NULL·좌표·가격·시각·편의 항목 하나라도 바뀌면 다시 검증한다. 총수·신선도·통계 metadata는 매 요청 현재 DB에서 읽어 전체 응답 DTO로 따로 검증한다. 입력+검증 출력 합계32MiB·최대8항목이며 큰 비교·검증·직렬화 동안 LRU 잠금을 잡지 않는다. 이는 Python RSS 상한이 아니다.

PG JSON 조회와 변환은 최대2건만 병행한다. 큰 검증·직렬화는 worker에서 처리해 event loop를 직접 막지 않는다. PG 회귀에서 codec을 대기시켜도 health가 응답하는 것을 확인했다. 검증 생략/model_construct·필드 축소·가격 이력 삭제·수집 변경은 없다.

## 실제 읽기 전용 비교

같은 MVCC의5,000곳7,360,652바이트를 교대 대조했다. 기존 구성의 API 프로세스 CPU7722/8010ms·wall10727/11146ms, 집합 투영 경로 CPU2724/2501ms·wall6308/8397ms였다. 전체 DTO 출력 SHA215909aa342fea949fe5d12a317a346b1419523ed71b4029f3be62384d737f1b가 같았다. DB 프로세스 CPU는 이 CPU 측정에 포함되지 않는다.

다음 같은 입력의 완료 검증 재사용 측정은 미사용5811ms/CPU3070ms, 비어 있던 검증 캐시4955ms/CPU1996ms, 재사용1781/2299ms·CPU158/150ms였다. 모두7,360,652바이트·SHA43361a2357ed21564a6a5c8ce74f572395171464bfc0966df4091cf9dfec2ca3가 같았다. 캐시 예산14,509,693바이트·격리 프로세스 peak RSS196,567,040바이트였다. ‘비어 있던 검증 캐시’는 DB/서버 cold가 아니다. 이는 저장 조회/검증/직렬화 구간의 단일 비교이며 실제 HTTP·p95·전국/1초 보장이 아니다. 실제 배포 후 같은 요청의 HTTP로 정산해야 한다.

초기 native 비교는 상세 진단이 없는 실패로 보존했다. 별도3행/5,000행 단독 조회는 동작 확인일 뿐 전후 동일성 근거가 아니며, 위 교대 대조에서만 전체 바이트 동일성을 확정했다. 실패 원인을 추정하지 않는다.

## 검증과 남은 단계

WSL SQLite33통과/PG 전용 worker시험1skip, WSL/Docker PG18각36통과다. 이후 최신 가격 변경이 TTL 없이 반영되는 API와 검증 캐시 집중5개를 두 환경에서 추가 통과했다. 겹친 시험 수는 합산하지 않는다. 단일 PG JSON 경로와 기존 복합 지도 경로를 같은 자료로 대조해 전체 DTO·시각/소수·NULL/0·유니코드/따옴표·B027/fallback·한쪽 잘못된 좌표·동일 시각 정렬·limit/truncated·빈 bbox·유종/출처 필터를 확인했다. digest 강제 충돌·변조한 날짜·용량/비잠금 검증도 확인했다. 최초 잘못된 음수 시험자료가 기존 DB CHECK에 거절된 원문은 보존했고 제약은 바꾸지 않았다. 소유 QA PG는 정확CID/label 검산 뒤 종료·제거했다.

최종 제품 commit/push·키 미노출 확인 뒤 같은 의존성의 새 API/수집기 이미지를 만들고 정상 Manager G→R/FD9에서 반영한다. API를 먼저 확인하고 수집기는 원20일정 capture/pause·실행/worker 자연 종료 뒤 교체한다. 기존 이미지·환경·원본·영구 통계와 공용 daemon/다른 서비스를 보존하며 백업/복원은 사용자 생략 지시를 유지한다. 실제 HTTP/PC모바일·원20복원/Manager·첫 부모 실제종료까지 완료 전에는 배포 성공으로 표시하지 않는다. Git 밖 원장은 weather-transport-read-next-20261107/plan.json과 native/QA 원문들이다.

## 실제 이미지 반영과 HTTP

제품 a8869693b84bf615007c17efb60e47b7a13984bf, 이미지 sha256:11418aa1e1a654fa1d09d85df1ec9984c94bdb4b040622d6dd320d7bb82d6c01이다. API CID67e9174ce347c5a9513e372eeef4056e8ad8a2cdd0b79a0b86e1a713c597be26, 수집기 CIDdee4b424b4d1e69229cc52d3888b622d7b1cbdfc959aa3fbdf2a82cde0fe942b가 healthy다. 실행 포트12302/12306, schema0041/SDK18864a3/Python3.12.13과 키·환경·원본·영구 통계를 보존했다. API 먼저 반영 후 기존 highway 수집의 자연 종료를 기다려 CS를 교체했다. 원20일정을 복원했고 Manager adopt/verify/show healthy, 첫Inv3cad34a9fdb7423b96c7bfa9d29d283e 실제done/Main0/cgroup부재·84자식 종료0을 확인했다. 백업/복원은 사용자 지시로 생략했다.

| 요청 | 첫 소유 관측 | 후속1 | 후속2 |
|---|---:|---:|---:|
| 5,000곳 HTTP+클라이언트 JSON 해석 | 12.79초 | 4.36초 | 4.03초 |
| 같은5,000곳 body 수신까지 | 12.09초 | 3.53초 | 3.33초 |
| 화면 범위756곳, limit900, 통계 포함 | 3.89초 | 1.31초 | 0.93초 |

5,000곳은 전체5,615곳 중 제한한 응답이며 truncated=true/clustered=false다. 매 요청 DB를 다시 읽었고 항목 SHA6001455b16f38831b6179731aef9f1eb643cfb1dfbd735c6ad9195fdb3a923bd가 같았다. 화면 범위756곳은 truncated=false이며 항목 SHA13c4424071877041425f50f1b755672090cf17703d09019997534b8d2da9d8a0이 같았다. health 포함7개 요청 모두200, 외부 수집/재시도0이다. 실제 cache hit는 계측하지 않았으므로 첫 요청을 cold, 후속을 확정 hit로 부르지 않는다. Weather export·기존 수집과 공용 호스트를 사용한 단일 표본이며 기존16.22/20.86초와 부하가 달라 p95나 코드 단독 개선율을 주장하지 않는다. 전체 응답1초 보장은 미달이다.

## 빌드 원문 보존

첫62e0f50b62/Invab644edb0bc944f0852966f3f8287b97은 Docker build0 뒤 native 소스 SHA 검산이 실패해 부모1로 종료했다. 최초 아카이브가 core.autocrlf 설정으로 CRLF 변환된 것이 실제 Git blob 대조에서 확인됐다. 실패 이미지a14a4bdf·아카이브3134ffc6은 배포하지 않고 보존했다. 별도R2는 core.autocrlf=false로 정본 LF를 만들고943파일의 Git blob을 검산했다. 정본 아카이브 SHAd692019697f8531ee38e26798fcc77751884a51c7b720e14d1848ea407ceb045, 첫Inv943b9e3a6cf0495c9411b8d16be46575 실제done/Main0/cgroup부재/native PASS와10자식 종료0이다. 제품 소스·기능은 바꾸지 않았고 종료 unit은 재시작하지 않았다.

## 최종 실제 화면 수용

n150의 Firefox157 PC1440/모바일375에서 실제 지도를 확인했다. 5유종 지역 대표 카드의 API/DOM 가격 일치, 지역 카드의 실제 클릭 가능한 지점으로 zoom8→12 전환, 새 단일 fuel PG 경로의 실제32/7개 항목과 DOM marker/지도 픽셀, 선택 LPG 가격/브랜드와 최근7일 그래프를 검산했다. PC 대명LPG충전소·모바일 신문혜충전소의 양수 가격이 같은 DTO와 일치했고 그래프가 각1개 표시됐다. overflow/pageerror0·logout303·브라우저 자식 종료·비공개 자격 파일 삭제를 확인했다. PC/모바일 확대 지도와 선택 상세 캡처를 실제 열어 검토했다.

첫 n150 실행은 시스템 Playwright driver CLI 부재로 화면 시작 전 실패했다. 기존 검증 패키지를 작업 전용 폴더에 두었으며 shared 설치/운영 서비스는 바꾸지 않았다. 별도 headless 관측은 WebGL 지도 표시 오류를 남겼고, Xvfb/소프트웨어 렌더링에서 WebGL2와 지도 픽셀을 확인했다. 다음 첫 marker center 클릭은 기존 지역 카드 겹침으로 다른 카드에 가려 실패했다. 원문은 보존하고 별도R4에서 elementFromPoint로 실제 가리지 않은 지점을 골라 클릭했다. force click·제품 변경·재배포는 없고 카드 겹침을 해결했다고 쓰지 않는다.

정본은 transport-large-map-release/final-acceptance.json, SHAd925169d3219584a9df8563401c0cf866f8e46ef15d7a4356ab7bbe6b3e63520. 실패 빌드·UI 원문과 실제 부모 종료를 모두 보존했다. MAP-LARGE-20261108의 구현·검증·실제 배포 수용은 완료이며 전체 응답1초/기존 겹침은 별도 미완이다.
