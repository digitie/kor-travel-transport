# 주소 갱신·응답 유실 재시도 최종 검증

최종 제품 3f5651772f7945e48b3d822898894f76814a69b4와 Common
89291f36d731ab906161b96757522e1cd833b4ef에 대해 두 독립 SOURCE PASS,
열린 P0/P1/P2=0이다. Common41은 f9148734b59023cec91ce8fdd44fad6f72d68322로 머지됐다.

VWorld 우선·Kakao fallback의 파생 주소를 위치별 KST 달력 6개월마다 갱신하며,
Admin 수동 요청은 같은 UUID의 native Dagster 실행을 재사용한다.
응답이 유실된 NOT_STARTED 실행은 제출을 복구하고, 새 mutation 미지원 서버는
실패를 반환한다. 원천 주소·좌표·수동 좌표를 덮어쓰지 않는다.
legacy 항구 제외 조건과 현재 원천 기준 확인 시각을 적용했다.

B·C의 r4 전체 검토와 r5 pin delta 검토를 원문 그대로 보존한다.
Common의 SQL 제한시간 보존 문제 때문에 보류했던 r4는 r5에서 닫았다.
제품 pin 변경 외 애플리케이션 코드는 r4 검토본과 같다.

최종 pin 집중23개와 공식 backend Docker 집중23개, 실제 loopback API·native
Dagster 연동 Chromium UI17개 및 12초 지연 후 재시도1개가 통과했다.
최종 제품 커밋의 CI backend·frontend·Admin이 push/PR 각각 통과해 6 SUCCESS다.
조건부 CI live-e2e 2 SKIPPED는 성공으로 집계하지 않으며 위 실제 loopback UI와 구분한다.
이전 a68의 로컬 전체 Python 실행은 pin 갱신 전에 의도적으로 중단했으며
KeyboardInterrupt/teardown 오류 결과를 성공으로 집계하지 않는다.
초기 opt-in 미설정 UI17 SKIP는 설정 수정 후17 PASS와 구분한다.

운영 migration·실 provider·외부 UI·ARM 전체 배포·수집 CPU/RSS는 NOT_RUN이다.
공용 webserver에 Common38+41의 단일 whole wheel을 먼저 적용하고 Admin을 배포한다.
Dagster daemon OFF를 유지한다. Track1·2 전체 수용 후 수집기 자원 사용을 측정한다.
이 문서와 원문 정산은 사용자 요청대로 CI를 생략한다.

## 원문·검증 무결성

| 파일 | SHA256 |
| --- | --- |
| [2026-10-18-native-address-native-validation.json](evidence/2026-10-18-native-address-native-validation.json) | 1cfe4ca8f9d80a6c161b30c2a1b5951142809f1a6143549f58ab9469cf5a5157 |
| [2026-10-18-native-address-r4-manifest.json](evidence/2026-10-18-native-address-r4-manifest.json) | a18256ee4805fbccd362dbd907e1549a08f58981277f232a1525c4ea53fd0a3c |
| [2026-10-18-native-address-r4-reviewer-b.md](evidence/2026-10-18-native-address-r4-reviewer-b.md) | c47c59d5c8a6fc4528a852436b68664c7bedfc61ca4a2df9bc4696ebe7b27db6 |
| [2026-10-18-native-address-r4-reviewer-c.md](evidence/2026-10-18-native-address-r4-reviewer-c.md) | cfd42192d708379bc6229cd593803cf4bbd137a4a9123cfab67d5fcf45c4714f |
| [2026-10-18-native-address-r5-delta.json](evidence/2026-10-18-native-address-r5-delta.json) | fc7216458e4ead688dd1abaf916eea7dc155aa67868331f30f3e9608a9f6f809 |
| [2026-10-18-native-address-r5-reviewer-b.md](evidence/2026-10-18-native-address-r5-reviewer-b.md) | 2ee36875ddf70cb937cd6bdd57d97feb92a9dd4a6ff6b8bc31b92a045af32ed4 |
| [2026-10-18-native-address-r5-reviewer-c.md](evidence/2026-10-18-native-address-r5-reviewer-c.md) | 5cad6e4b5e5e93cfac042f62dbd6616ea547d04c431eb321a415775c6adc630e |
| [2026-10-18-native-address-source-ci.json](evidence/2026-10-18-native-address-source-ci.json) | 9aec7e156d2fe684817c92c19cd8d17a039b3d58c6ce0001f30a19d6fd7b255d |
