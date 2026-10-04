# Transport 격리 live UI 검증

- 날짜: 2026-10-04 KST, 담당: 원 구현자 Codex.
- runtime candidate: `781723356e3f73ae2f48f8df831b3a6970a898e3`.
- common Python: `430a9e9cd5429204579792b1d4f8e399366dcb2f`.
- 실제 설치된 common Dagster 모듈 SHA256:
  `3fb1df0f98dc1d6828bb25db10ce3e1c3605fae7619fa3080ac2d240228cc979`.
- 관리자 빌드 source `cf30bcfc36277a26f03e0f682d5ec6f1b9672e2b`와 최종 후보의
  관리자/공개 frontend tree는 `git diff --quiet`로 동일함을 확인했다.
- 전용 compose project `codex-transport-recovery-20261004`, PostgreSQL 16, Dagster 1.13.24,
  production Next 관리자, loopback 전용 포트와 SSH tunnel. 운영 compose/DB/provider는 변경하지 않았다.
- UI 동작은 CUA in-app browser로 수행했다. 운영 배포 테스트로 집계하지 않는다.

## 관찰

| 시나리오 | 실제 결과 |
|---|---|
| 로그아웃 → 공통 로그인 폼 | 로그인 화면 이동 |
| 잘못된 테스트 비밀번호 | 일반 오류 표시·비밀번호 입력 초기화 |
| 정상 로그인·공통 메뉴 Dagster 이동 | 세션 생성·현재 메뉴 Dagster 하나 활성 |
| 소유 location 실행 조회 | 실패 1·장시간 실행 1·스케줄 12/12 표시, foreign 실행 제외 |
| 실패 상세 | 실제 native RUN_FAILURE 메시지·terminal 경과 시간 표시 |
| 정체 표시 | 5시간 이전 STARTED 이벤트·4시간 runtime tag로 정체 의심 표시 |
| 스케줄 상세 | 한국어 label·5분/4시간/8시간 표시·원본 cron·location 범위 native URL |
| 320/375/414/768/1440 폭 | 페이지 가로 overflow 없음, 좁은 표 내부 scroll |
| 키보드 표 진입 | region tabindex 0, ArrowRight로 표 scrollLeft 40 확인 |
| 전용 Dagster 중지 → 새로고침 | 조회 오류와 다시 시도 표시, 마지막 12/12·두 실행 결과 유지 |
| 최신 코드로 Dagster 복원 → 다시 시도 | 오류 해제·확인 시각 갱신·조회 버튼 다시 활성 |
| 실패 실행 native 링크 | 실제 airport_collection_job FAILURE·STEP_FAILURE·RUN_FAILURE 이벤트 화면 |
| 최종 서비스 reload | 기존 인증 세션과 두 실행·12개 스케줄 정상 조회 |

실패 probe는 외부 provider를 호출하지 않는 전용 op를 실제 Dagster에서 실행한 이벤트다.
장시간 probe는 전용 metadata에 STARTED 이벤트의 과거 시각을 기록했다. 실제 운영 worker를
kill하거나 5시간 기다렸다는 의미가 아니다. 전용 daemon은 실행하지 않아 예약/복구 sensor가
provider를 자동 호출하지 않았다. 센서 평가와 장애·복원은 아래 코드 테스트로 별도 검증했다.

## 설치·코드 검증

- 전용 런타임의 recovery sensor 4개: worker 회수, 공항·고속도로·휴게소 인프라 재시도.
- 같은 wheel의 common recovery 56 tests: PASS, 전용 tmpfs metadata 경로에서 20.19초.
- 최신 transport PostgreSQL/Docker 복구·definitions·runtime 경계 29 tests: PASS, 63.23초.
- 관리자 Docker 146 tests, 공개 UI Docker 130 tests: PASS. 디스크 대기를 고려한 worker 1 실행.
- WSL 전체 SQLite 회귀: 647 passed·9 skipped. 최신 wheel 재설치 후 경계 29 tests도 PASS.
- 최신 후보 PostgreSQL CI: 655 passed·1 skipped, migration upgrade/check·OpenAPI export PASS.
  [완료 CI](https://github.com/digitie/kor-travel-transport/actions/runs/37185005593).

초기 KRIC deferred 수와 proxy 정적 계약 실패를 수정했다. 임시공간 부족·example 파일
복사 누락·NTFS chmod 동작으로 실패한 로컬 실행은 최종 Linux 파일시스템 회귀로 다시 확인했다.
격리 서버의 이전 전체 PostgreSQL 실행은 54% 이후 오래된 후보와 디스크 대기로 중단했다.
이를 PASS로 세지 않고 최신 후보 전체 CI 및 서버의 복구 경계 실행 결과를 각각 기록한다.

## 캡처

- [데스크톱](2026-10-04-transport-dagster-desktop.jpg):
  SHA256 `fc9a3c01f9a3e4a2a041eb207b1a2ff44c6d8b02224c38fad87f18b57a5f217d`.
- [모바일](2026-10-04-transport-dagster-mobile.jpg):
  SHA256 `525455fe7cab0bf4c8ae8b35275a0d6e92166301fdfd261d6bd7aa9f1ada9212`.
- [조회 장애](2026-10-04-transport-dagster-outage.jpg):
  SHA256 `17f8726d6b4bfec2014160a8eb8522dbce74780d6e5aa39d1e92cf15640da375`.
- [native 실패](2026-10-04-transport-native-failure.jpg):
  SHA256 `be511fdcf2eb001884f6c4b29f9678394b9357869d4d541279c991c6b6f85841`.

운영 shared coordinator 적용·운영 daemon/launcher worker 강제 종료·운영 RSS는 NOT_RUN이다.
