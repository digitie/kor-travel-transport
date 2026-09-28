# PR #51 검증과 배포 기록

## 최종 상태와 읽는 순서

운영 API/code-server `fcd4d1f`, UI `55148d2`에서 유가 단일 수집 성공·관리자 E2E
421개·parking-radar E2E 16개 통과를 확인했다. Provider PR #20은 자체 최종 CI·
독립 리뷰·운영 수집 검증 후 **2026-09-29 08:05 KST**, `7e0f770`으로 머지했다.
검증한 `5fa0046`은 main 이력에 보존했고 소비자 pin은 바꾸지 않았다.
Transport PR #51은 최종 문서 커밋의 필수 CI를 확인한 뒤 머지한다. 이미 머지된
PR은 반복하지 않으며 최종 상태는 각 PR이 정본이다. 아래 항목은 시간순 검증 이력으로,
당시의 보류·실패를 기록한 것이지 추가 수집·재배포 지시가 아니다.

## 변경과 범위

- 항만가이드라인 첫 항로 점을 승선 항구 좌표로 사용하지 않는다.
- KOMSA 공식 기항지 API와 TAGO 코드의 명시 연결 19개를 정확 이름·시도로 검증한다.
  전체 항구 위치 완료가 아니며 미확인 항구를 임의 좌표로 표시하지 않는다.
- 정상 재검증의 무결과·중복·부적합 좌표는 이전 연결을 해제하고 일시 실패만 보존한다.
- 교통 탭의 높이/버튼 충돌, 열린 겹침 목록의 viewport 재조회 취소, 타일 실패의
  SVG 디코딩 오류, 최초 묶음 초기화 누락을 수정한다.
- VWorld 키는 로컬 Map 설정에서 Git 제외 `.env.local`로 가져와 빌드에 주입했다.
  실제 키·인증 URL·예외 원문은 문서에 기록하지 않는다.

## 선행 라이브러리

- `python-kric-api` PR #9 병합 `2690f354`: provider 163개 통과·live 2개 제외,
  독립 James/Popper 리뷰 및 인천 단건 실제 조회 확인. Transport에서는 기항지 job만 호출한다.
- `maplibre-vworld-react` PR #29 병합 `fb754755`: 기존 초기화 회귀 2개 실패를
  재현하고 수정 후 웹 E2E 전체 5개 통과, 타입·빌드·린트 통과(기존 경고 13개).
  저장소에 GitHub Actions 설정은 없다. 독립 두 리뷰 완료, consumer에서 별도 검증한다.

## 로컬·CI 검증

| 환경 | 결과 |
| --- | --- |
| WSL 백엔드 전체 | 340개 통과·4개 환경별 제외 |
| WSL Docker Compose 백엔드 전체 | 340개 통과·4개 환경별 제외 |
| 최종 quota 보강 범위 WSL / Docker | 각각 47개 통과·2개 PostgreSQL 전용 제외 |
| 전용 PostgreSQL | 동시 예약·상한·재검증·quota·Dagster 30개 통과, Alembic drift 없음 |
| backend 후보 `dc6ba5f` GitHub CI | PostgreSQL 포함 351개 통과 |
| 관리자 WSL / Docker Compose | 각각 111개 통과, 린트·타입·운영 빌드 통과 |
| 기존 parking-radar WSL / Docker | 각각 85개 통과, WSL 빌드 통과 |
| 수정 라이브러리를 결합한 WSL HTTPS UI | 421개 통과, 재시도·제외 없음(3.8분) |

UI 행렬에는 실제 저장 DB 조회·인증/gateway와 모의 응답 기반 오류/경계 상태가 함께 있다.
421개 모두 외부 제공자 실호출을 한 것은 아니다. 초기 HTTP 테스트의 Secure 쿠키
인증 실패는 로컬 HTTPS로 검증 경로를 바로잡았고 보안 정책은 완화하지 않았다.

## 독립 적대 리뷰

- James(Mill): 타일 지연 실패의 SVG 오류 및 정상 타일에서도 최초 묶음이 없는 문제를
  분리 재현했다. 수정 후 최초 4묶음의 즉시/지연 성공·실패 네 조건을 독립 실행해
  디코딩 오류·로딩 잔존 없이 표시됨을 확인했다. 카메라 조작으로 결함을 숨기지 않았다.
- Popper(Helmholtz): 정상 무결과의 과거 좌표 잔존, 출력/신호 단절 시 배포 복구 중단,
  검증 이미지와 후보 SHA 연결 누락을 지적했다. 각각 수정하고 재리뷰에서 차단 없음.
  고정 이미지·OCI revision·소스 84개 지문을 확인했고 복구 모의 실행 8개를 통과했다.
- 라이브러리 최초 load 이력 수정은 두 리뷰어가 독립 검토했다. Popper의 fixture
  타이밍 제안은 명시 복원 버튼으로 반영해 느린 환경의 거짓 통과도 방지했다.

## n150 운영 검증

API/code-server 후보는 `dc6ba5f7266a635535bfc0a9b849cafc499539d0`, 검증 이미지 digest는
`4d4e1bb72b94c34c907d46100fc70afb6bbbffc19195698a53fad3610633741a`다. 운영 Dagster
1.13.24를 유지하며 기존 이미지 위에 검증 소스/provider만 반영했다. 네트워크 없는
후보 컨테이너에서도 변경 범위 44개 통과·PG 전용 2개 제외를 확인했다.

backend/code-server 제한 교체와 원래 daemon 재개 후 모두 healthy를 확인했다.
보호 컨테이너 ID·이미지·시작 시각 불변 검사를 통과했다. 되돌림 자료는
`/home/digitie/transport-pr51-rollback.ET4C1m`에 보관한다. 72시간 관찰 중 prune은 하지 않는다.

기항지 job은 식별 태그 `pr51-komsa-port-call-dc6ba5f-once`, run
`cf5c1d60-48ac-496f-a565-ec6aaf11db70`으로 한 번 실행했다. 항구 749·터미널 27·
선박 종류 7·RustFS 원본 1개를 저장했고 공식 좌표 10개를 연결했다. 정상 응답
14회(10개 연결·4개 무결과), 한도 오류 5회로 부분 성공이며 Dagster 실패를 유지한다.
quota 카운터를 초기화하거나 추가 실호출로 확인하지 않았다.

이후 서비스 전체 24시간 유예를 보강한 API/code-server `840f5854c7118f2c1d68c53ae54f7e8311aecb04`를
image `e1dddd1e0738348bd3f4ba62da2fa324dcb059fac0620d00697d990cd741afaa`로 배포했다.
독립 이미지/소스 지문 확인 및 네트워크 없는 후보 47개 통과·2개 제외를 거쳤다.
되돌림 자료는 `/home/digitie/transport-pr51-rollback.qmuZrU`에 있다.
실제 DB의 READ ONLY transaction에서 HTTP client 없이 유예를 확인했고 호출 예약은
검증 전후 19건으로 불변이다.

관리자 UI 후보는 `55148d2c94cc6b80ce6c757f713fa6972853fb83`, 이미지 digest는
`fe4f3fe65e443e6826fafa56114fba2864bb1f3b2713dc2d4acd72971bf15ce9`다.
관리자 웹만 교체했고 되돌림 자료는 `/home/digitie/transport-pr51-ui-rollback.5bpAcW`다.
API/code-server/daemon/UI는 모두 healthy·재시작 횟수 0이다. 보호 서비스는 불변이다.

최종 backend `840f585` / UI `55148d2` 조합에서 운영 HTTPS E2E **421개 통과**
(4.1분, 재시도·제외 없음). James도 실제 VWorld 배경·인천 마커·공식 위치 안내와
저장 시간표 41편, 320/390px 넘침 없음·상세 포커스 복원을 독립 확인했다.

## 추가 운영 게이트와 머지 보류

기존 parking-radar 전체 live 검사에서는 **15개 통과·1개 실패**였다. 실패는 통합
교통 API 최신성 검사로, `opinet_browser.last_success_at=2026-09-26T15:36:34Z`가
17시간 기준보다 오래됐다(검사 시 약 48시간). 기준을 완화하거나 검사를 제외하지 않았다.
주차 UI·실제 수집 최신성·반응형 검사는 통과했다.

오피넷 마지막 시도는 `2026-09-28T07:01:12Z`, 표시 오류는 `collection_failed`,
다음 허용 시각은 `2026-09-28T15:24:00Z`다. Popper의 읽기 전용 진단 결과는 다음과 같다.

- DB 수집 `19387`은 9/28 16:01:12~16:24:00 KST 실행 후 `failed`다.
  저장 오류는 `Timeout 60000ms exceeded while waiting for event "response"`다.
  대응 Dagster run `536082e3-aa6d-4103-9117-c79e0a45b793`은 `SUCCESS`로 표시됐다.
- DB 수집 `19582`는 9/29 00:00:35 KST에 `skipped`다. 대응 run은
  `b53622dc-1576-4b6f-802f-16d4e1ba55ff`다. 실패 종료 뒤 8시간 유예가 00:24까지라
  0시 정기 실행이 허용 시각보다 빨랐다. 다음 정기는 08:00 KST이며 성공은 미확정이다.
- `transport_collection.py`의 `_mark_fuel_failure()`는 provider의 8시간 간격을 적용한다.
  `dagster/definitions.py`의 `_collect_transport()`/fuel op는 반환된 실패 상태를
  Dagster 예외로 전환하지 않는다. 이 경로는 PR #51 변경 대상이 아니었다.
- 기존 저장 로그로 사이트 지연·응답 조건 불일치·접근 차단 중 timeout 근본 원인을
  구별하지 못했다. 이번 지도 변경과의 인과관계는 발견하지 못했다.

위 읽기 전용 진단 중 추가 provider 호출·수집 실행·재시작·설정 변경은 없었다.
이후 사용자가 유가 복구 범위 확대를 승인했으며 아래 후보를 검증 중이다.
따라서 [Transport PR #51](https://github.com/digitie/kor-travel-transport/pull/51)은
전체 게이트 성공으로 보고하거나 머지하지 않는다. 최종 CI·머지 상태 정본은 PR이다.

## 유가 복구 후보 검증

- Transport `fcd4d1f`, provider `5fa0046`([PR #20](https://github.com/digitie/python-opinet-api/pull/20)).
  기존 전국 수집의 response timeout 원인은 아직 미확정이며 진단을 위해 호출 간격을 줄이지 않는다.
- Dagster 실패·부분 성공의 잘못된 성공 표시 4건을 재현했다. 수정은 성공분 commit과
  provider close 뒤 실패를 전달하며 자동 재시도하지 않는다. 성공·건너뜀 포함 8개 회귀가 통과했다.
- 공개 검색 문서 1회 GET에서 `The service is not available.` HTTP 200 오류 HTML을
  확인했다. 동일 문서 회귀 2건을 재현 후 provider에서 조기 실패하도록 수정했다.
  이 관찰을 과거 response-wait timeout의 원인이라고 단정하지 않는다.
- provider의 응답 대기 실패에는 단계·숫자 지역 코드·최근 8개 document/xhr/fetch
  요청 이벤트만 추가한다. query·헤더·본문·원 예외 문자열은 이 진단에 포함하지 않는다.
- 실제 Chromium의 모의 GET/POST 불일치 검증과 provider WSL/Docker 각각 259개 통과·
  live 4개 제외, 커버리지 93.45%, 타입 검사 통과. GitHub Python 3.11~3.13·타입 검사도 통과했다.
- 두 독립 적대 리뷰에서 신규 P0/P1 없음. 이미지 실패가 핵심 이벤트를 밀어내는 P2는
  필터·12회 실패 회귀로 수정했다. 비숫자 지역 구분과 응답 이후 DOM 진단 P2는 제한을
  문서화하고 tasks에 남겼다. Transport의 기존 오류 마스킹은 유지한다.
- 관련 WSL/Docker 55개씩 통과·PG 전용 2개 제외, 전용 PostgreSQL 38개 통과·Alembic drift 없음.
  최종 후보 WSL 전체는 356개 통과·6개 환경별 제외, GitHub PostgreSQL 전체는 362개 통과다.
  n150 후보 이미지의 network-none 관련 검사는 89개 통과·3개 환경별 제외다.
- 후보 이미지 `5676cf9c62a72a9fa204f3455cd4181ebc9504b807b91c620316fd1f89887abf`와
  `fcd4d1f`의 OCI revision·backend 파일 84개 지문·실제 provider 소스 일치를 Popper가 확인했다.
- 배포·단일 수집 helper 재리뷰에서 code-server의 미설정 RELEASE_SHA 대신 이미지/revision을
  검사하도록 수정했다. 고정 호스트 잠금, 실패 union/run ID 검사도 보강했다. 독립 mock
  14개와 실제 커널 잠금을 사용하는 별도 프로세스 동시성 검증을 통과했다.
- Docker 전체 검사의 첫 시도는 테스트 시작 전 중첩 read-only mount 실패였다. 전체 검증
  root를 별도 경로로 마운트하도록 바로잡아 전체 **356개 통과·6개 환경별 제외**를 확인했다
  (16분 29초, 종료 코드 0). provider Docker 초기 환경의
  테스트 의존성·import root·패키징 쓰기 경로 누락도 격리된 전체 dev 환경으로 바로잡고
  위 259개 통과를 확인했다. 이 준비 실패를 제품 테스트 통과로 계산하지 않았다.
  n150에 backend/code-server만 교체하고 두 서비스 healthy·재시작 0, 원래 daemon
  이미지 유지·재개·healthy·재시작 0과 보호 서비스 불변을 확인했다. 되돌림 자료는
  `/home/digitie/transport-pr51-rollback.2cAk5G`다.
- 배포 후 단일 유가 run `83c635f8-1bf4-4216-a5aa-113efe51245f`을 실행했다.
  식별 태그는 `pr51-fuel-recovery-fcd4d1f-once`다. 실행 전 8시간 보호가 열려 있고
  유가 대기/실행 job이 없으며 provider `5fa0046`인 것을 확인했다. 당시 수집 결과는
  확인 중이었다. 이후 실제 수집·운영 HTTPS E2E 결과는 아래에 기록했다.
- 신규 배포 후 첫 운영 HTTPS E2E는 **417개 통과·4개 실패**(7분)다. 4개 모두 항공편
  상태 검사 이전 `beforeEach`의 `/login` 탐색에서 `ERR_NAME_NOT_RESOLVED`로 실패했다.
  같은 WSL에서 이후 DNS A 응답과 HTTPS 200을 확인했다. 원 실패 trace를 보존하고
  해당 4개와 전체 검사를 재검증했다. DNS 우회·TLS 무시·테스트 자동 재시도는 추가하지 않았다.
- DNS 정상화 후 해당 4개는 16.5초에 모두 통과했고, 같은 운영 후보의 전체 재검증도
  **421개 통과**(8.5분, 재시도·제외 없음)했다. 최초 실패 trace는 `pr51-prod`,
  대상 재검증은 `pr51-dns-targeted`, 전체 재검증은 `pr51-prod-final`에 별도 보존했다.
- 독립 운영 점검: Popper는 실제 API release·양쪽 provider commit·소스 84개 지문·
  원래 daemon과 보호 서비스 상태를 확인했다. James는 실제 Chrome에서 지도와
  320/390px 가로 넘침 없음을 확인했다. 이 결과는 유가 최신성 회복 판정과 분리한다.
- 07:22 KST 읽기 전용 점검에서 이번 DB run `19750`은 `running`이었다. 최근 성공한
  유가 run 18543/18088/17280의 소요시간은 각각 39분 02초/51분 23초/52분 01초다.
  30분 경과만으로 비정상 지연을 단정하지 않으며, 과거 소요시간을 현재 성공의 증거로
  사용하지 않는다. 해당 조회는 read-only transaction·10초 statement timeout으로 제한했다.
- 단일 유가 run은 **SUCCESS**, DB `19750`도 **success**로 종료됐다. DB 종료는
  07:48:47 KST, Dagster 종료는 07:48:56 KST이며 전체 실행은 약 56분 31초다.
  마지막 성공과 최신 가격 저장 시각은 **07:32:56 KST**, `last_error`는 해제됐다.
  다음 허용 **15:32:56 KST**로 8시간 보호를 유지한다. 이번 원본 요약은 지역 7,905·
  주유소 11,767개, DB 주유소 전체는 11,846개다. 최신 가격 행 수 집계는 독립 조회의
  10초 제한으로 실패해 미확인이다. 과거 timeout의 근본 원인이 규명됐다는 뜻은 아니다.
- 수집 종료 직후 parking-radar live 검사는 **14개 통과·2개 실패**다. 첫 화면의 주차
  목록이 20초 안에 표시되지 않았고, 통합 API 검사는 마지막 교통 run이 `running`인
  상태가 120초 동안 유지됐다. 유가 노후와는 다른 실패이며 최신성·응답 기준을 낮추지 않는다.
  n150에서 I/O·메모리 압력을 관측했고 여유 공간은 약 101GB였다. 한 번의 관측만으로
  지연 원인을 확정하지 않는다. 다른 서비스 재시작·DB 변경·prune은 하지 않았다.
- 주 에이전트의 읽기 전용 가격 최댓값 진단도 오래 걸렸다. 확인된 진단 PID만 종료하도록
  준비했지만 실행 직전 해당 프로세스가 자연 종료했고, PID 존재 guard에서 중단돼
  실제 종료 신호는 보내지 않았다. 결과는 위 갱신 사실과 일치하며 이후 진단에는
  10초 statement timeout을 추가했다. 이 진단 지연을 운영 게이트 성공으로 계산하지 않는다.
- 고속도로 DB run `19774`는 07:59:56 KST에 정상 종료했다. 이어 저장 주차 목록은
  약 0.01초로 응답했다. 상태가 회복된 것을 확인한 뒤 같은 운영 후보·같은 검사를
  재실행해 parking-radar **16개 모두 통과**(24.4초)했다. 첫 화면은 2.1초, 통합
  API·유가 최신성 검사는 6.5초에 통과했다. 테스트 코드·최신성 기준·timeout은
  바꾸지 않았고 수집이나 스케줄을 강제로 실행/중지하지 않았다. 최초 실패 결과는
  `pr51-live`/`pr51-live-first.json`, 최종 trace 출력 위치는 `pr51-live-final`로 구분했다.
- 이로써 실제 유가 복구·관리자 421개·parking-radar 16개 운영 검증이 완료됐다.
  provider PR #20은 자체 CI·리뷰·실수집 게이트 통과 후 `7e0f770`으로 먼저 머지했다.
  Transport PR #51만 최종 문서 커밋의 필수 CI 확인 후 머지한다.
  최종 CI·머지 여부는 각 PR을 정본으로 확인한다.
