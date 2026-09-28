# PR #51 검증과 배포 기록

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

진단 중 추가 provider 호출·수집 실행·재시작·설정 변경은 없었다. 이번 지도/항구
범위를 넘어선 유가 수집 복구는 사용자 방향 확인 전 실행하지 않는다.
따라서 [Transport PR #51](https://github.com/digitie/kor-travel-transport/pull/51)은
전체 게이트 성공으로 보고하거나 머지하지 않는다. 최종 CI·머지 상태 정본은 PR이다.
