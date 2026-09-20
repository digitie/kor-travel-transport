# KRIC 신청 대상과 라이브러리 구현 계획

확인일: 2026-09-20. 사용자가 직접 신청할 목록이며, 이 문서 작성으로 신청하거나 키를
발급하지 않았다. `F:/dev/python-kric-api`는 기존 GitHub 저장소를 clone한 상태로,
초기 commit `c65a8b7`에는 README와 LICENSE만 있다. **라이브러리는 아직 미구현**이다.

## 공식 제공 범위

[파일 목록](https://data.kric.go.kr/rips/M_01_01/intro.do)은 확인 시점 1,210건,
[Open API 목록](https://data.kric.go.kr/rips/M_01_02/intro.do)은 60건이었다.
목록 개수는 변동 가능하며 전국 모든 운영기관의 동일한 최신성·완전성을 뜻하지 않는다.
파일 목록에는 기관별 CSV/XLS/XLSX뿐 아니라 PDF·이미지도 있으므로, 모든 첨부를
하나의 표 파서로 처리하지 않는다.

## 우선 신청 목록

모든 아래 경로의 API 기본 주소는 `https://openapi.kric.go.kr/openapi/`다.
공통 인증 인자는 `serviceKey`, 출력 형식 인자는 `format`이며 JSON/XML을 제공한다.

| 우선순위 | 서비스와 공식 신청 화면 | 경로 | 용도와 주요 입력 |
|---|---|---|---|
| 1 | [역사별 정보](https://data.kric.go.kr/rips/M_01_02/detail.do?id=183&operation=stationInfo&service=convenientInfo) | `convenientInfo/stationInfo` | 위치·주소·다국어 역명. `railOprIsttCd`, `lnCd`, `stinCd`, `stinNm` |
| 1 | [도시철도 전체노선정보](https://data.kric.go.kr/rips/M_01_02/detail.do?id=431&operation=subwayRouteInfo&service=trainUseInfo) | `trainUseInfo/subwayRouteInfo` | 노선 구성역과 순서. `mreaWideCd`, `lnCd` |
| 1 | [역사별 운행시각표](https://data.kric.go.kr/rips/M_01_02/detail.do?id=182&operation=stationTimetable&service=convenientInfo) | `convenientInfo/stationTimetable` | 출발·도착, 시발·종착역. 운영기관/노선/역 코드와 `dayCd` |
| 1 | [열차별 운행시각표](https://data.kric.go.kr/rips/M_01_02/detail.do?id=162&operation=subwayTimetable&service=trainUseInfo) | `trainUseInfo/subwayTimetable` | 열차번호별 시각표. 운영기관/노선/역 코드와 `dayCd` |
| 1 | [편의정보](https://data.kric.go.kr/rips/M_01_02/detail.do?id=426&operation=stationCnvFacl&service=convenientInfo) | `convenientInfo/stationCnvFacl` | 승강기·화장실·수유실 등 위치. 운영기관/노선/역 코드 |
| 2 | [열차별 운행시각표(급행), 역사별 승강장](https://data.kric.go.kr/rips/M_01_02/intro.do) | `trainUseInfo/subwayTimetableExp`, `convenientInfo/stPlf` | 급행 구분과 승강장 보강. 각 상세 계약 확인 후 구현 |
| 2 | [역사별 혼잡도](https://data.kric.go.kr/rips/M_01_02/detail.do?id=197&operation=stationCongestion&service=convenientInfo) | `convenientInfo/stationCongestion` | 서울교통공사 평일 자료, 측정주기 분기. 전국·주말·실시간 혼잡도로 해석하지 않음 |
| 2 | [환승·이동경로·엘리베이터](https://data.kric.go.kr/rips/M_01_02/intro.do?page=2) | `convenientInfo/stationTransferInfo`, `convenientInfo/stationElevator`, `vulnerableUserInfo/stationMovement`, `vulnerableUserInfo/transferMovement` | 교통약자 환승 동선. 이동 방향/인접역 인자까지 별도 확인 |

같은 이름의 일반/표준 API는 별개 서비스다. `handicapped/*`와 `convenientInfo/*`를
동일 응답으로 가정하지 않는다. 위 입력 목록은 공식 명세의 항목을 정리한 것이며,
생략 가능 여부·최대 결과 크기는 승인 후 최소 요청으로 검증한다.

## 신청·quota·이용허락 주의사항

[공식 신청 절차](https://data.kric.go.kr/rips/serviceInfo/openapi/process.do)는 회원가입과
인증키 발급, 하나의 키로 여러 API 이용, 과도한 트래픽 제한 가능성을 안내한다.
확인한 페이지에는 고정 일일 횟수나 TPS가 명시돼 있지 않다. **임의의 quota를 공식값으로
기재하지 않는다.** 신청 화면에서 서비스별 승인 범위, 기간, 일일 한도, 재배포 조건을
확인하고 운영 기록에 남긴다. 조회한 핵심 상세 페이지의 이용허락은 저작권표시다.

- 키는 `KRIC_SERVICE_KEY` 등 로컬 비밀 설정으로만 취급한다. 인증 URL·응답 진단에
  키가 포함되지 않게 한다. 다른 provider의 키를 KRIC 키로 가정하지 않는다.
- 초기 구현은 동시 요청 1개, 보수적인 송신 간격과 호출 수 상한을 둔다. 이는 자체
  안전장치이지 공식 허용량이 아니다. 인증/권한/한도 오류에서 자동 반복하지 않는다.
- 철도역·노선 기준정보는 일/주 단위, 시각표는 영업일·개정 버전 기준으로 먼저 설계한다.
  실시간 도착정보나 운행중단정보가 이 시각표 API에서 제공된다고 가정하지 않는다.

## 파싱 계약과 완료 기준

1. `CLAUDE.md → AGENTS.md → SKILL.md → docs/architecture/ → docs/resume.md` 진입
   구조와 한국어 문서·feature branch/Draft PR·두 적대적 리뷰 정책을 이 저장소에서
   계승한다. 공항 웹앱 전용 경로와 Docker 운영 지시를 라이브러리 실행 지시로 잘못
   복사하지 않고, 적용 범위를 명확히 기록한다.
2. `src/kric/`에 비동기 HTTP, 파싱/모델, 오류, 공식 API 목록을 분리한다. 소비자 서비스의
   DB·스케줄러는 이 라이브러리에 넣지 않는다. 통합 앱 내부에 KRIC 파서를 중복 작성하지 않는다.
3. 역 identity는 운영기관+노선+역 코드로 보존한다. `stinCd` 단독 전역 ID나 역명 병합을
   사용하지 않는다. 코드 선행 0을 유지한다. 역 기준정보와 경로 구성 항목을 분리하고,
   `routCd` 등 경로 그룹별로 `stinConsOrdr`를 해석한다. 경로 그룹/순서의 유일성 및
   같은 역의 반복 등장을 실제 표본으로 검증한다. 여러 경로를 한꺼번에 정렬하거나
   분기·환승을 역명 문자열 정렬로 복원하지 않는다.
4. 위경도 `stinLocLat`/`stinLocLon`과 X/Y 지도좌표 `mapCordX`/`mapCordY`를 구분한다.
   후자는 CRS·단위가 명세에 없어 미확인이다. 확인 전 투영좌표나 위경도로 단정하거나
   변환하지 않는다. 잘못된 좌표는 원본과 오류를 함께 남긴다.
5. `dayCd`의 공식 의미는 7=토요일, 8=평일, 9=휴일이다. 도착/출발 시각은 날짜 없는
   영업일 시간으로 우선 보존한다. 자정 이후·빈 값·비정상 시각 규칙은 실제 표본 확보 전
   datetime으로 임의 변환하지 않는다.
6. 파일 목록/상세 페이지와 공개 첨부 파서는 API 클라이언트와 구분한다. 허용된 공개 링크만
   사용하고 로그인·CAPTCHA를 우회하지 않는다. 파일 형식·인코딩·필수 열·최대 크기를 검사하고
   출처 URL/기준일/해시를 보존한다. CSV/XLSX와 PDF·이미지를 별개 지원 상태로 표시한다.
7. 네트워크 없는 계약 테스트와 실제 응답을 분리한다. 문서로 만든 합성 표본을 live fixture라
   부르지 않는다. 키 승인 후 역사/노선/시각표/편의정보 각각 최소 실제 요청, 원문→모델
   재생 테스트, WSL/Docker 테스트, 독립 리뷰 후 구현 PR을 머지한다.

현재 완료: 공식 목록·핵심 상세 명세 확인, 신청 대상 정리, 로컬 clone.
남은 작업: 작업 규칙/패키지 뼈대, 공개 파일 파싱, API 구현, 테스트, 승인 키로 live 검증,
GitHub 구현 PR. 이 문서는 구현 완료 보고가 아니다.
