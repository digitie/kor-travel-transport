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
| 재검증 후 변경 범위 WSL / Docker | 각각 44개 통과·2개 PostgreSQL 전용 제외 |
| 전용 PostgreSQL | 동시 예약·상한·재검증·Dagster 28개 통과, Alembic drift 없음 |
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
`cf5c1d60-48ac-496f-a565-ec6aaf11db70`으로 한 번 요청했다. 저장 결과·관리 UI
후보 `55148d2` 배포·운영 HTTPS 검증은 아직 진행 중이며 최종 결과를 아래에 추가한다.
