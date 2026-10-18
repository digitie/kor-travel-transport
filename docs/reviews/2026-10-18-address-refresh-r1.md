# Transport 주소 갱신 최초 FULL 독립 리뷰

상태: POST_FIX_REVIEW. **r1 A SOURCE PASS / B REQUEST_CHANGES**, 당시 OPEN P2 1개와 비차단 P3 1개를 보존한다.

base61a566dee0b1cc40f858652c0683883c26e56411 → 제품f8e5dd06f8bfe478fdb57785e70b2304958333ad.
[동일 manifest](evidence/2026-10-18-address-refresh-r1-manifest.json),
[A 원문](evidence/2026-10-18-address-refresh-r1-reviewer-a.md),
[B 원문](evidence/2026-10-18-address-refresh-r1-reviewer-b.md)을 byte 그대로 보존했다.
실제 요청 원문·관찰 hash·격리·시각·검증/미실행 한계는 각각의 원문에 있다.
A/B는 서로의 새 결과를 원문 확정 전에 보지 않았다.

- T86-B-P2-01: 기존 지도에서 무효로 취급하는 data_go_kr_port_guideline의 FerryPort 좌표를 새 source가 조회하고 정상 파생 결과로 게시했다. 원본 mutation은 없지만 유효 좌표 admission 계약에 맞지 않아 REQUEST_CHANGES했다.
- A P3: UI13개는 두 viewport를 합한 앱당 수량인데 문구가 viewport마다13개처럼 읽힌다.

작성자는 legacy 신규 조회와 기존 파생 결과 노출을 실제 모델·공통 엔진 SQLite로 각각 재현(2 FAIL)했다.
FerryPort branch에 기존 제외 조건을 적용하고 NULL/수동 좌표를 유지한다. 새 immutable commit의 두 독립 재검토/CI는 별도다.
이 기록이 수정 후 PASS나 운영 배포를 대신하지 않는다. Daemon OFF를 유지한다.
