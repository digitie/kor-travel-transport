# Transport 주소 갱신 두 번째 FULL 독립 리뷰

상태: POST_FIX_REVIEW. **r2 A SOURCE PASS / B REQUEST_CHANGES, OPEN P2 1개**를 보존한다.
기준 base61a566dee0b1cc40f858652c0683883c26e56411 → 제품8c89e1a72d92b54865bb0f2db553c1c2cfe17561.
[r1 기록](2026-10-18-address-refresh-r1.md), [같은 manifest](evidence/2026-10-18-address-refresh-r2-manifest.json),
[A 원문](evidence/2026-10-18-address-refresh-r2-reviewer-a.md),
[B 원문](evidence/2026-10-18-address-refresh-r2-reviewer-b.md)을 byte·SHA256 그대로 보존했다.

- 원 T86-B-P2-01 legacy 항만 admission은 양쪽이 CLOSED로 확인했다. NULL/admin_manual을 보존하며 예전 sidecar/원천을 삭제하지 않는다.
- A의 P3는 앱당 UI13이 두 viewport 합계라는 guide 문구 수정으로 CLOSED다.
- 새 T86-B-P2-02: Common c067 summary의 resolved_at MAX가 현재 원천 join 없이 provider 전체를 읽어 제외된 항만의 확인 시각을 노출한다. A의 PASS로 B의 OPEN을 덮지 않는다.

작성자는 공통 엔진에서 삭제·제외·경도/위도 이동·더 최근 orphan 반례 5 FAIL을 재현했다.
[Common40](https://github.com/digitie/kor-travel-common/pull/40)의 현재 source·좌표 집계 수정
522525aed3db934767c1c9e742b3bfc68e91679c를 소비자 pin으로 채택하고 별도 legacy-only 시각 회귀를 추가한다.
원 c067에서 소비자 반례1 FAIL을 확인했다. 후속 candidate의 CI·두 독립 검토·최종 수용은 별도이며 이 원문은 당시 판정이다.

8c PR CI39092813701은 PostgreSQL848 PASS/2 SKIP/910.63초, frontend/Admin SUCCESS다.
r2 manifest 작성 시 중복 push39092810095는 진행 중이었으며 그때 PASS로 집계하지 않았다.
실제8c Docker 집중21·loopbackUI13·PGdrill은 통과했고, fullDocker835/13은 이전6a 기능 baseline이다.
운영 migration/provider/배포/UI·CPU/RSS는 미실행이고 Daemon OFF다.
