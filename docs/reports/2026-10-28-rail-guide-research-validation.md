# 철도 연결 사전 조사·설계 문서 검증

## 현재 결과와 미완 범위

역 안내→출발/도착 조건→예정 시간표의 연결, provider별 확정 ID, 시설·전화의 지원/미확인 범위를
[조사](../research/2026-10-28-rail-guide-connection.md)와
[단계A/B 설계](../design/2026-10-28-rail-guide-timetable-connection.md)로 정리했다.
웹과 공식 Android/iOS 설명을 기존 화면 조사와 구분했으며 앱 설치/로그인/예매/전화/실제GUI는 실행하지 않았다.
현재 구현은 anchor만 있고 자동 prefill이 없다. facilities[]도 시설 부재를 의미하지 않는다.
소비자 흐름은 기존 지도/검색/시간표 구조를 유지하고 외부 API도 동일 provider·도시·원문ID를 검증한다.

문서 전용 변경이며 제품·SDK·provider·DB·스케줄·운영·prune0이다. A/B 구현은 후속 작업이다.
원본48시간/통계영구 PR161/162/163과 독립하며 이 문서가 해당 정책을 완료하지 않는다.

## 정합성 점검2회와 독립 리뷰

1차는 source40파일의 SHA/Git blob/줄 수와 실SDK pin2개, Guide anchor/임시ID/시설[],
Journey 독립 TAGO 선택·cold catalog·공용비재진입lock·기본15초/SDK3transport시도를 원문과 대조했다.
2차는 문서의 식별자/상태enum/API·UI동일성, 시설미지원·미수집·부분·실패 구분과 제안/실제 관측을 교차 점검했다.
동일 이름/거리 자동 매핑0·수동 선택의 비전역성·누적 deadline·dependency 순서/잠금 해제·취소/상한 회귀와
operation/SDK/HTTP 호출 수의 구분, 모든 상대 링크도 확인했다. 자체 점검은 독립 리뷰를 대신하지 않는다.

원R1 packet `rail-guide-connection-research-20261028-r1/review-manifest.json` SHA
`6b974bd2e80074303e63e5f91cbffef01ad1f4aaeb1c14c2c0cf74572b835a2c`와 원37source·두 점검·Popper P2는 보존했다.
새R2 packet SHA `89f8b8716762f380b8637714ee4a79fedec3666cdcde8367f64956562295d56b`는
같은 commit의 근거3파일을 추가하고 설계3.3의 비재진입 잠금·요청 전체 예산 P2를 보완한다.
packet과 검산 스크립트는 로컬 증거이며 repository의 실제 source는
[40파일 원장](../research/2026-10-28-rail-guide-source-manifest.json)의 commit/Git blob으로 고정한다.

정확 `dfd7de50e67c1630e7b1e9cc2330fd26a7399e43`의 문서8파일·원R1 대비 P2 보완에 대한
독립 Popper SOURCE_PASS를 회수했다. 보고서 SHA256은
`25bc89dc20a137698e2b144695b3f9b25db46149c8cfb6d6ba7db93cc637068a`다.
이후 변경은 완료된 리뷰 상태의 정정뿐이며 조사·설계·source 원문은 그대로다.
사용자 지시대로 문서PR은 CI 결과를 기다리지 않고 정합성2회·독립 리뷰 및 상태 정정 증분 확인 뒤에만
머지하며 merge는 Root가 결정한다. 실제 UI/API·배포 테스트나 기능 구현이 완료된 것으로 표현하지 않는다.

## 자료와 설계의 정확한 경계

Transport source3f516, KRIC실pin5bf0/Datagokr실pin69c8을 로컬 Git object로 조회했다.
stale KRIC 로컬 HEAD553을 실지원으로 쓰지 않았고 fetch0이다. Root의 기존15098552 서울→부산75편 성공은
당시 SDK 관측이며 이후편69는 시각 의존 값이다. 현재 GUI나 고정 기대값/전국 모든 등급 성공으로 확장하지 않는다.
같은 이름의 KORAIL/TAGO/KRIC/SRT를 자동 매핑하지 않는다. KRIC 시설 API를 일반철도/KTX/SRT 시설로 대입하지 않는다.

설계3.3은 향후 cold 준비에서 query의 fetch 안으로 다른 query를 재귀 배치하지 않도록 한 제약이다.
현재 source에 실제 deadlock이 발생했다고 주장하지 않는다. 요청 전체15초 기본 예산과 operation≤4/SDK메서드≤5는
제안 계약이며 SDK retry/redirect를 포함한 실제 HTTP 전송 수와 다르다. 실제 적용·동등성/시간 예산 회귀는 B 구현 때 필요하다.
공식 근거가 없는 crosswalk/시설가동 상태·새provider활용권한·SDK의 미확인 응답은 그대로 미검증이다.
