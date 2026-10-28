# 철도 연계와 시설 정보: 조사 근거·누락

이 문서는 정확 source의 사실, 공식 설명, 기존 실제 SDK 관측, 설계 추론을 구분한다.
공식 설명은 해당 앱의 현재 동작·우리 API 성공을 보증하지 않는다.

## 1. 고정 source에서 확인한 사실

Transport 기준은 `3f5160a0d5e0c246fa744864998a3fc805542ce4`다. 경로는 각 저장소 기준이며 줄 번호는
[고정 source40파일 원장](2026-10-28-rail-guide-source-manifest.json)의 Git blob 기준이다.
[최소 연결 설계](../design/2026-10-28-rail-guide-timetable-connection.md)와
[검증 범위·남은 gate](../reports/2026-10-28-rail-guide-research-validation.md)를 함께 읽는다.

| 근거 | 확인 사실 | 사용자에게 남는 문제 |
|---|---|---|
| `components/general-rail-guide.tsx:14–15,30–42` | `provider_id`·공개 `station_code`·주소·전화·좌표를 받지만 `Place.id=index+1`, `facilities: []`로 변환 | 이 숫자 ID는 DB 역 ID나 TAGO ID가 아니다. 시설이 없다고 판정할 수 없다. |
| 같은 파일 `47–59` | 초기 지도, 분류·역 검색·선택 범위 근처10역, 주소 지도 focus, `#general-rail-timetable` 링크 | 초기 분류 미선택의 빈 items는 의도다. 전국 근처역 검색이나 시간표 prefill은 아니다. |
| 같은 파일 `64–65` | 전화 `tel:`·공식 역 안내 링크와 시간표 anchor | 역 지정 callback은 없다. 원문 전화에서 모든 비숫자를 제거하므로 복수 번호·내선은 별도 안전 검토 대상이다. 실제 복수번호 관측을 주장하지 않는다. |
| `components/general-rail-journey.tsx:16–36,40–55,84–91` | 출발/도착은 독립 TAGO 지역·검색 후보를 직접 선택한다. Guide에 props를 전달하지 않는다. | 지도에서 찾은 역을 두 번째로 탐색해야 한다. 지도 선택을 TT 조건으로 자동 연결한 코드가 없다. |
| 같은 파일 `63–82,91–95` | 조건 변경 취소·명시 조회·KST 일자·30초 이후편 필터, 실시간/잔여석 미제공 안내 | 기존 안전 동작을 연결 과정에서 보존해야 한다. 실제 TT 데이터를 가짜 결과로 바꾸지 않는다. |
| `backend/app/general_rail_routes.py:81–132` | catalog·city별 stations·TT 캐시/검증. TT는 저장 station catalog에 ID가 있어야 하고 `date`·grade를 검증 | 현재 외부 API는 정확한 ID만 알아도 cold catalog에서 404가 가능하다. UI만 callback으로 고치면 API 사용 흐름은 그대로 불편하다. |
| 같은 파일 `133–155`; `schemas.py:649–666` | Guide API는 코레일 typed model을 투영한다. 빈 category면 categories만 반환하고 items는 [] | 시설·TAGO 연결 상태·공식 링크는 API 계약에 없다. frontend의 공식 링크만 외부 API 사용자에게 제공되지 않는다. |
| `backend/app/main.py:1607–1608`, `models.py:479–512` | 도시/광역철도는 저장 전화와 SDK의 공개 파일 시설 파서를 사용한다. 원문 JSON·기준일 보존 | 일반철도 Guide의 시설[]과 도시철도의 제한적 시설 목록을 혼동하면 안 된다. |

추가 고정 원문 대조: `general_rail_routes.py:26–35,54,62–69,78–104,130`은 catalog/stations/timetable이
같은 비재진입 TAGO lock과 query 보호를 쓰고, catalog callback은 city/class 두 SDK 메서드를 호출한다.
`backend/app/core/config.py`의 기본 api_timeout_seconds는15이며 현재 query가 요청 전체 deadline을
이미 적용했다고 확인한 것은 아니다. SDK pin69c8 `transport.py:46–61`은 transport 실패의 최대3시도와
공용 TPS 대기를 두고 `services/openapi.py`의 train 메서드는 이 계층을 소비한다. 따라서 cold 준비를
잠금 내부 callback에 재귀 배치하거나 operation96을 실제 HTTP96회라고 표시하면 안 된다.
향후 순서·누적 시간 예산·검증 조건은 설계3.3절에 명시한다. 이 사실은 추가 provider 호출 없이 확인했다.

현재 UI에 지도·전화·공식 링크가 없다고 결론내리지 않았다. 지도는 실제 분류/역 선택 상태에서
확인할 대상이고, 이 조사에서 생산 화면을 실행하지 않았다.

## 2. 실 pin SDK의 지원 범위

Transport `backend/uv.lock:1005,1009,1758,1816`의 pin을 로컬 Git object로 읽었다.

| 계층·근거 | 확인된 지원 | 확인되지 않았거나 지원하지 않는 것 |
|---|---|---|
| KRIC pin5bf0 `src/kric/korail_public.py:27–36,119–140` | `KorailStationGuide`의 station_sequence/name/address/phone/category, 선택적 station_code/좌표 | facility 필드·TAGO ID·SRT 고유 역 목록은 이 모델에 없다. |
| 같은 파일 `220–240`; SDK `docs/korail-public-station-guide.md` | 같은 공개 제공자 안에서 유일한 정확 역명끼리만 좌표 보조 연결. KTX 분류는 노선, main은 권역 | 같은 이름을 TAGO/KRIC/SRT에 교차 연결하는 근거가 아니다. 분류 목록은 선로 형상·정차 순서도 아니다. |
| KRIC pin5bf0 `src/kric/client.py:116–125`, `models.py:108–117` | `get_station_facilities`는 기관·노선·역 3코드로 `convenientInfo/stationCnvFacl` 조회. 반환은 `StationFacility.values` 원문 mapping | 일반철도/KTX/SRT 시설 성공 계약이나 현재 운영/고장 정보는 확인하지 않았다. SDK 메서드 존재를 실제 수집 성공으로 표시하지 않는다. |
| SDK `README.md:22–25,219–224`, `files.py:419–429` | 파일1294의 환승·유실물 취급·안전발판·스크린도어·승강장 연결 중 명시 긍정 값만 tuple로 제공 | 화장실·수유실·물품보관함·승강기 위치 전체를 의미하지 않는다. 빈 tuple은 시설이 없다는 뜻이 아니다. |
| TAGO pin69c8 `src/datagokr/models.py:300–329` | 도시 code와 `nodeid`/이름, 차량 code, 예정 출도착/요금 | 역 좌표·주소·전화·시설·코레일 stationSeq 교차표는 이 typed 역 모델에 없다. 예정표는 잔여석/실시간 지연이 아니다. |

SDK 시설 parser는 응답 식별 필드를 요구한다. 공식 문서의 출력 표와 실제 응답 필드의 완전 일치는
본 조사에서 생산 호출하지 않아 미검증이다. 필요하면 SDK에서 실제 자료와 typed 계약을 먼저 보강한다.
Transport에서 HTML/JSON 우회 파서를 새로 만들지 않는다.

## 3. 공식 웹·Android/iOS 자료 대조

기존 `docs/research/2026-10-25-mobility-ux.md`의 코레일+ iOS 화면·SR 가이드·접근성·사용 맥락 조사를
재사용했다. 그 문서의 과거 source 결함을 현재 source에 그대로 적용하지 않고 위 코드로 재대조했다.
이번 추가 조사는 공식 설명·HTML 문서를 읽은 것이며 앱 설치·로그인·실제 터치 검증은 아니다.

| 공식 자료 | 확인 범위와 얻은 설계 근거 |
|---|---|
| [코레일+ Android](https://play.google.com/store/apps/details?hl=ko&id=com.korail.talk), [iOS](https://apps.apple.com/kr/app/id1000558562) | 양쪽 설명은 여정과 열차 조회·연계 이동을 연결한다. 선택 위치 권한으로 가까운 역을 찾는다고 안내한다. 지도 탐색에서 출발/도착 조건으로 넘어가는 흐름과 권한 거부 시 직접 검색을 유지할 근거다. 예약·결제/추천 홈을 복제할 근거는 아니다. |
| [SRT Android](https://play.google.com/store/apps/details?id=kr.co.srail.newapp&hl=ko), [iOS](https://apps.apple.com/kr/app/id1350286957) | 양쪽 설명에 지도형 출·도착역 선택이 있다. 지도 역을 검색 조건으로 지정하는 행동을 가져온다. 잔여석·승무원 호출은 앱 기능 설명이며 우리 TAGO 지원으로 이전하지 않는다. 이전 통합/앱 명칭 안내만으로 SRT의 현재 데이터 범위를 확정하지 않는다. |
| [SR 수서역 공식 안내](https://etk.srail.kr/cms/archive.do?pageId=TK0403010100) | SRT역과 지하철 환승통로·출구·주차 안내가 구분된다. 같은 ‘수서’ 이름/가까운 점이 같은 서비스의 승강장·시설·접근 경로를 뜻하지 않는 실제 복합역 반례다. 해당 역 안내를 전국 자료나 실시간 주차 잔여로 확대하지 않는다. |
| [KRIC 시설 명세426](https://data.kric.go.kr/rips/M_01_02/detail.do?id=426&service=convenientInfo&operation=stationCnvFacl) | 제공기관은 전국 도시철도 운영기관, 요청은 기관·노선·역 코드다. 시설 구분·층·상세 위치·교통약자 구분을 명세한다. 시설 존재와 무장애 경로/현재 가동을 구별해야 한다. API 샘플 URL은 호출하지 않았다. |
| [KRIC 철도 통합정보](https://station.kric.go.kr/v2/altmInfoSys/index.do) | 지역·노선·역 선택 뒤 시설·이용안내도·출입구/교통약자 경로를 구분한다. 화면의 아이콘을 모든 역의 실제 데이터로 간주하지 않는다. |
| [공공데이터포털15098552](https://www.data.go.kr/data/15098552/openapi.do) | 출발·도착 기반 예정표, 차량·도시·시도별 역 목록을 설명한다. 공식 설명에 KTX 포함이 있어도 모든 SRT 편/좌석/실시간 지연 지원을 입증하지 않는다. |
| [코레일 공식 역 안내](https://www.korail.com/ticket/train/stationGuide/station/view?stationSeq=10281321) | 이번 열람은 서비스 이용 안내 화면으로 대체되어 역 상세/시설은 확인하지 못했다. 우회하거나 숨은 endpoint를 탐색하지 않았다. 공식 링크의 존재와 현 제공 자료의 정확성은 별개다. |

### 추가 자료 후보: 아직 소비하지 않는 공식 API

‘현 pin에 필드가 없다’는 이유로 공식 자료가 전혀 없다고 결론내리지 않았다.

| 공식 명세 | 실제 필요한 정보와의 관계 | 미확정·다음 검증 |
|---|---|---|
| [한국철도공사 임대매장정보15125773](https://www.data.go.kr/data/15125773/openapi.do), [공식 조회 안내](https://openapis.korail.com/samples/public/lease/stores) | 매장 위치·역사층수·주소·평일/휴일 영업시각을 명세한다. 기다리는 동안 이용할 매장 확인의 후속 후보이며, 조회 안내의 역코드는 별도3자리 문자열이다. | `stor_stn_cd` 코드정보를 따르며 TAGO/공개 stn_cd와 같다고 추정하지 않는다. 화장실·승강기/현재 영업을 대신하지 않는다. 실자료/활용 권한/SDK 지원은 미확인·미호출이다. |
| [한국철도공사 열차운행정보15125762](https://www.data.go.kr/data/15125762/openapi.do) | 주운행선·정차·상하행 code와 역 code의 명시적 자료 후보다. ‘권역’을 선로 노선으로 표시하는 빈틈을 장기적으로 보강할 수 있다. | `stn_cd` 코드정보와 별도 범위/보존기간을 명세한다. 현재 열차 지연·모든 SRT 지원이나 TAGO 교차표를 확인한 것은 아니다. 기존 성공한15098552의 대체/재신청 요구가 아니며 실조회하지 않았다. |

후보 자료를 쓸 때는 해당 provider 라이브러리의 담당 경계를 먼저 확인해 typed 기능을 개선한다.
키 없는 KorailPublicClient와 다른 인증/보호 계약을 섞거나 backend에 새 HTML wrapper를 넣지 않는다.
현재 A/B 연결 개선에 이들 새 API 도입을 필수 의존으로 걸지 않는다.

## 4. 이미 확인된 실제 자료와 이번 미실행

Root의 기존 SDK 증거 `C:/Users/digit/.codex/tmp/tago-timetable-root-20261028-r1/result.json`은
15098552 승인 키로 16도시 및 서울(NAT010000)→부산(NAT014445)의 당시75편/유효75편 성공을 기록했다.
그 시점 이후편69는 관측시각에 의존하는 과거 수치다. 이번에 재호출하지 않았으며 GUI/API 전체 성공,
전국/모든 등급 성공으로 확대하지 않는다. 승인 질문을 반복할 이유가 없다.

## 5. 실제 이용자 관점에서 남는 결정

| 상황 | 먼저 필요한 정보·행동 | 설계상 지켜야 할 구분 |
|---|---|---|
| 익숙하지 않은 여행지에서 가까운 역 탐색 | 지도/목록에서 위치·접근 위치 확인 → 출발로 지정 | 현재 ‘선택 분류 안 가까운10곳’과 전국 가장 가까운 역은 다르다. 거리만으로 접근 가능을 보장하지 않는다. |
| 목적지 역만 정함 | 도착역 지정 → 기존 출발/날짜를 유지 → 예정편 | 지도 조작 때문에 출발/도착 두 값을 동시에 바꾸지 않는다. |
| 이미 표를 가진 사람·마중 | 정확한 서비스/역 위치·주소 지도·연락처·공식 안내 | 예약·잔여석 조회를 새로 만들 필요가 없다. 대표 고객센터와 역 직통을 구분한다. |
| 유모차·휠체어·고령자·큰 짐 | 필요한 시설 종류뿐 아니라 층·상세 위치/해당 승강장 접근·확인 연락처 | 시설 존재가 현재 가동·연속 무장애 경로를 보장하지 않는다. metro 시설을 KTX/SRT 시설로 표시하지 않는다. |
| 동명이역·복합역·역명 변경 | 제공자/도시/확정 ID와 구체 주소를 후보 확인에 사용 | 유사 이름·suffix 제거·가까운 좌표·이름 유일성만으로 자동 연결하지 않는다. |
| 일반열차/고속열차 취향, 빠른 편/이후 편 | 공식 차량 종류·출발/도착·예정시각/요금·조회시점 | Guide의 KTX 노선/main 권역을 TAGO 차종 code로 변환하지 않는다. |
| 위치 거부·느린 연결·큰 글씨/키보드 | 직접 역 검색·오류 재시도·선택 맥락 유지·키보드 지정 | 긴 안내로 지도를 밀지 않는다. 새 스코프에 늦은 옛 응답이 역을 덮지 않아야 한다. |

따라서 새로 필요한 핵심은 거대한 역 정보 카드가 아니라 **확정 역 참조·지정 의도 전달·원문 범위가
명시된 시설/연락처·수집 시점과 미지원 상태**다. 확인되지 않은 교차표와 운영 중 시설 상태는 별도 수집 근거가 필요하다.

공식 원문별 확인 범위는 [공식 자료 메모](2026-10-28-rail-guide-primary-notes.json)에 남겼다.
