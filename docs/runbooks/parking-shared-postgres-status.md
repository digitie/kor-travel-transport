# parking-radar 공용 PostgreSQL 운영 확인

## 결론 — 추가 이전은 필요하지 않음

2026-09-28 16:47~16:49 KST, UI PR #47 머지(`bdc9c02`) 후 사용자 요청에 따라 실제 운영
연결을 확인했다. `parking-radar`는 이 저장소의 기존 주차 웹앱 브랜드이며 Transport와
같은 backend를 사용한다. 주차 데이터는 이미 공용 Docker PostgreSQL에 저장되고 있다.
이번 확인에서는 덤프/복원, DB 생성/삭제, DSN 변경, 컨테이너 재시작을 하지 않았다.

## 실제 연결 경로

| 구성 요소 | 운영 연결 |
|---|---|
| 기존 `kor-travel-airport-frontend-1` | `BACKEND_INTERNAL_URL=http://127.0.0.1:14001` |
| `kor-travel-airport-backend-1` | `127.0.0.1:11000/kor_travel_transport`, role `kor_travel_transport_app` |
| Dagster code-server | application DB와 동일한 공용 DB |
| Dagster metadata | `127.0.0.1:11000/kor_travel_transport_dagster` |
| DB 컨테이너 | `kor-travel-shared-postgres`, host network, healthy |

DSN 비밀번호는 출력하거나 문서에 기록하지 않았다. `docker inspect`에서 주소·포트·DB명·
계정만 추출했다. application DB에 앱 계정 연결 6개, metadata DB에 3개가 관측됐다.
이 연결 수는 점검 시점의 값이며 고정된 운영 조건이 아니다.

## 실제 주차 데이터와 권한

공용 DB에서 읽기 전용 transaction과 15초 statement timeout으로 조회했다.

| 대상 | 실제 `count(*)` |
|---|---:|
| 공항 | 14 |
| 주차장 | 53 |
| 주차 관측 | 735,925 |
| 주차 요금 규칙 | 32 |

- 주차 관측 범위: 2026-08-15 01:41:00~2026-09-28 07:45:03 UTC
  (최신 2026-09-28 16:45:03 KST).
- Alembic: `0015_fuel_statistics_priced`.
- `public` 테이블 24개 모두 `kor_travel_transport_app` 소유.
- 앱 role의 superuser/createdb/createrole은 모두 false.
- 점검한 운영 Docker 목록에 별도 parking/airport PostgreSQL 컨테이너는 없었다.
  이는 과거 데이터 디렉터리까지 삭제됐다는 뜻이 아니다. 이번 작업은 디스크를 삭제하지 않았다.

## 웹앱 확인

`https://pr.digitie.mywire.org`에서 기존 live E2E 5개가 6.7초에 통과했다.

- 실제 주차 자료 표시, 공항 선택 유지, backend health와 수집 최신성.
- 320/375/414/768px 홈 화면의 가로 넘침 방지.
- 백업 화면은 열기만 검증했다. 백업 생성·복원은 실행하지 않았다.
- API release는 기존 `ff45aeac9cdbfd16a9e969a954b8402651c625d5`를 유지했다.

## 운영 정본과 재이전 방지

Docker Manager의 최신 `origin/main` `68cc1a9`을 읽기 전용으로 대조했다. 해당 저장소의
`config/docker-targets.yml`은 `airport`가 공용 `kor_travel_transport` DB를 사용한다고
명시하며, `docs/shared-postgres-onboarding.md`의 2026-09-28 현황도 동일하다.
로컬 Manager checkout `7d6917f`와 미추적 파일은 변경하지 않았다.

따라서 옛 DB를 추정해 복원하거나 새 parking 전용 DB를 만들지 않는다. 이후 실제 DSN
이전이 필요해지면 Manager 온보딩 절차에 따라 원본 확인·백업·복구 리허설·writer 동결·
행 수/시퀀스 검증을 수행한다. 공용 instance 재시작이나 다른 tenant 변경은 별도 범위다.
