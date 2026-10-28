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

## 머지 전 잔여 게이트

- 독립 적대적 리뷰 두 명 및 정확 최종 head CI.
- 1440/375의 실제 후보 UI에서 상세 버튼·작은 지도 외곽 유지·초점/스크롤·지역/실제 후보 확인·시간표 요청 확인.
- 실제 지원 구간으로 API와 화면 조회 성공 수용. 과거 SDK의 서울→부산 편수는 이 변경의 GUI 성공 근거가 아니다.

현재 기능 코드는 구현했지만 머지·운영 배포·실제 UI 수용 완료는 아니다. 단계 B와 시설 보강도 완료로 세지 않는다.

## 동결 소스 지문

- `packages/kor-travel-transport-admin/frontend/components/general-rail-guide.tsx`: `6d0f116fc52f876ba28125315bbe1f2673e37d973ef0d6d1ba617fcae3ad6f1f`
- `packages/kor-travel-transport-admin/frontend/components/general-rail-journey.tsx`: `cd2c21ffa45b13939fc0768d693286a54bc0dc3df0c65589af48ffc5d43c7055`
- `packages/kor-travel-transport-admin/frontend/components/general-rail-station-intent.test.tsx`: `33c15ea8ce72e14500f794b5d372067201e367850d74c33af5830220a0c016b2`
