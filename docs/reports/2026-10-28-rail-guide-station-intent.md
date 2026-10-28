# 철도 안내 역의 출발·도착 지정 단계 A 검증

## 구현과 사용 흐름

기준 main은 `8d80dd1f23601254fdfecdb344212ff7a89cf00c`(조사 문서 PR166)이다.
선택한 역 상세의 작은 `출발로 지정`·`도착으로 지정` 버튼을 기존 TAGO 검색에 연결했다.
안내의 `provider=korail_public_guide`·`provider_id`는 지도 선택의 안정 참조이며,
시간표용 `station_id`로 변환하지 않는다. 노선의 응답 순서가 바뀌어도 같은 안내 역은 같은 지도 마커 식별자를 유지한다.

지정은 해당 쪽의 이름 검색어만 채우고 이전 확정 선택을 해제한다. 지역을 고르지 않았다면 기존 지역 선택에 초점을 준다.
반대쪽 확정 역, 출발일, 열차 종류, 지도 노선/권역·검색·목록/지도 상태·지도 초점은 유지한다.
실제 TAGO 목록의 후보 버튼을 눌러야 시간표 조건이 확정된다. 후보가 하나거나 같은 이름이어도 자동 선택하지 않는다.
지역을 바꾸면 진행 중인 목록을 취소하며 늦은 응답을 숨긴다. 뒤늦은 목록 도착은 다른 입력으로 옮긴 사용자의 초점을 빼앗지 않는다.
새 지정으로 시간표 조건이 바뀌면 이전 요청도 취소하며 이전 결과를 새 조건에 표시하지 않는다.

새 대형 폼·API·provider 호출 규칙·SDK·DB 변경은 없다. 도시와 역의 백엔드 종속 참조 준비·전체 deadline은
[설계 단계 B](../design/2026-10-28-rail-guide-timetable-connection.md)로 남는다.
`facilities=[]`의 지원 범위를 확대하지 않았으며 일반철도/SRT 시설 데이터나 물리적 동일역 교차표를 제공하는 것으로 표시하지 않는다.

## 실제 검증

모든 실행은 별도 WSL 소스/캐시와 소유 Docker 자원으로 수행했다. 운영·provider·DB 호출은0이다.
원장: `/var/tmp/rail-guide-intent-20261028-7dba3e678c10`.

| 검증 | 실제 결과 | 범위 |
|---|---|---|
| WSL 원본 RED | 5실패·exit1 | main8d80 + 새 테스트5만 적용, 실패 원문 보존 |
| WSL 후보 | 14통과·exit0 | 새 의도 연결5 + 기존 검색2 + 지도7 |
| WSL 타입/린트 | 각각 exit0 | 타입7.625초·린트8.586초 |
| WSL Next 빌드 | exit0·15.018초 | 실제 Next 빌드, 소스 전후 SHA 동일 |
| Docker 후보 | 14통과·exit0 | 같은 세 파일, 독립 `docker wait` exit0·값0·컨테이너 부재 |

WSL Node22.22.2와 Docker Node22.23.1을 구분한다. 두 환경 npm12.0.1·동일 package-lock으로 설치했으며 의존성/lock 변경은 없다.
Docker는 `compose run --rm --no-deps`로 network none/1CPU/2GiB/256PID를 적용했다.
소유 이미지 `rail-guide-intent-qa:7dba3e678c10`의 ID는
`sha256:ebadb391c8cbfef7a11c7d01e3ea4eb630e1ff029d3f1e65f627d1131c91ef7e`이다.

첫 Docker QA이미지 빌드는 저장소 `.dockerignore`가 임시 npm 패키지의 내부 `node_modules`를 제외해
`MODULE_NOT_FOUND`·실제 exit1로 실패했다. 원로그는 `docker/build`에 보존했다.
새 `docker/build-r2`는 **QA 전용** `Dockerfile.qa.dockerignore`로 임시 npm 패키지를 포함해 실제 빌드 exit0을 회수했다.
제품 Dockerfile·ignore·패키지 파일에는 변경이 없다. 두 실행 모두 기준 이미지 ID와 제품 소스 SHA가 불변이다.

반례는 서로 다른 Guide/TAGO 식별자·동명이인 두 후보·단일 후보의 명시 확인·재지정·도시 변경 중 늦은 응답·
이전 시간표 응답·서로 다른 입력 간 초점·순서가 바뀐 안내 응답을 포함한다. TransportMap은 컴포넌트 테스트에서 모형이므로
이 결과가 실제 VWorld 타일·모바일 지도의 시각 검증을 대신하지 않는다.

## 실제 Next·Firefox 후보 미리보기

`14e9e4e`의 같은 세 소스 지문과 WSL 빌드 원장을 `BUILD_ID=oloEdr6KqSfObhvb7tFsv`에 연결해
소유 loopback Next 서버에서 Firefox1440×900·375×900을 순차 실행했다. **FIXTURE_PREVIEW이며 운영/API 성공 증거가 아니다.**
TAGO 서울 `NAT010000`·부산 `NAT014445`는 앞선 실제 SDK 관측 ID를 사용했지만, DTO는 browser-route 대역이다.
Guide ID/좌표·추가 동명 후보·시간표 두 행은 명시적 시험 자료다. provider나 backend에 전달하지 않았다.

최종 `fixture-preview-r5/result.json`은 실제 exit0이며 각 화면16개, 합32개 항목을 통과했다.
실제 상세 버튼·Enter 지정·기존 지역 선택 초점·동명 두 후보/유일 후보의 명시 클릭·반대역/날짜/차종 보존·
지연 목록 응답의 초점 방어·Guide 순서 반전 후 선택·지도/목록 왕복과 새 큰 폼 부재를 확인했다.
pageerror0·가로 overflow0, 두 세션 로그아웃200·쿠키0이다.

| 화면 | 필터가 열린 초기 지도 | 지정/왕복 후 지도 | 문서 폭 |
|---|---|---|---|
| 1440 | 1118×732, y155 | 1118×732, y155 | 1440 |
| 375 | 349×575, y316 | 349×719, y172 | 375 |

모바일의 정상 필터 접힘은 지도 높이를 늘린다. 원R1/R2의 필터 선택자/접힌 필터 접근,
R3의 열린 상세 뒤 목록 클릭, R4의 지도 높이 동등 기대 오류를 원실패로 보존했다.
R5는 사용자가 누르는 정상 필터 펼치기·상세 닫기를 사용하고 지도 면적이 감소하지 않는지 검산했다.
이 과정에서 제품 코드는 바꾸지 않았다.

프리뷰 R1~R5마다 실제 서버 종료와 loopback 포트 폐쇄·로그아웃 쿠키0을 검산했다.
최종 Firefox/서버의 기록된 PID/startticks 생존0·소유 자식0이다. 서버의 의도적 SIGTERM 종료는 Next exit143으로 기록하며
이를 검증 실행 exit0과 구분한다. 암호·session secret은 RAM에서 생성/전달했고 파일·argv·HAR에 저장하지 않았다.
최종 원장·스크린샷6개·cleanup은 같은 QA namespace의 `fixture-preview-r5`에 있다.

빌드에 공개 VWorld 키가 없어 실제 canvas0이고 키 부재 fallback을 캡처했다. **타일·카메라 중심/줌 동작은 미검증**이다.
이미지 면적·기존 지도 작업면과 폼의 보존 결과를 실제 지도 엔진 성공으로 확대하지 않는다.

## 머지 전 잔여 게이트

- 독립 적대적 리뷰 두 명 및 정확 최종 head CI.
- 1440/375 실제 Next/Firefox 대역 미리보기32항목은 위와 같이 통과했다. 실제 VWorld 타일·카메라 및 운영 API 수용은 별도 미완이다.
- 실제 지원 구간으로 API와 화면 조회 성공 수용. 과거 SDK의 서울→부산 편수는 이 변경의 GUI 성공 근거가 아니다.

현재 기능 코드와 로컬 대역 UI 미리보기는 검증했지만 머지·운영 배포·실제 데이터/지도 수용 완료는 아니다. 단계 B와 시설 보강도 완료로 세지 않는다.

## 동결 소스 지문

- `packages/kor-travel-transport-admin/frontend/components/general-rail-guide.tsx`: `6d0f116fc52f876ba28125315bbe1f2673e37d973ef0d6d1ba617fcae3ad6f1f`
- `packages/kor-travel-transport-admin/frontend/components/general-rail-journey.tsx`: `cd2c21ffa45b13939fc0768d693286a54bc0dc3df0c65589af48ffc5d43c7055`
- `packages/kor-travel-transport-admin/frontend/components/general-rail-station-intent.test.tsx`: `33c15ea8ce72e14500f794b5d372067201e367850d74c33af5830220a0c016b2`
