# TAGO 일반철도 역 보강

## 누락 원인과 보강 범위

KRIC 전체에 일반철도 정보가 없는 것은 아니다. [공식 철도역 정보](https://file.kric.go.kr/jsp/board/portal/sub05/est/estationList.jsp)는
일반철도·KTX역을 별도로 제공한다. 현재 수집 중인 dataset1294는 전국 **도시·광역철도** 파일이다.
2026-11-09 운영 DB의 기존 source1108건에는 전주·순천·익산·안동이 없었다.

이미 고정된 `python-datagokr-api`의 [TAGO 일반철도 API](https://github.com/digitie/python-datagokr-api/pull/20)를
재사용한다. 실제 운영의 일반철도 catalog 조회는200·지역16개·stale=false였다.
provider HTTP·인증·TPS·응답 파싱을 새로 구현하거나 SDK를 재설치하지 않는다.

## 저장과 실패 경계

기존 `rail_station_references`에 `source=tago_train`, `identity_key=tago_train:<nodeid>`로 추가하고
공식 역 코드는 `station_number`에 그대로 저장한다. 지역별 raw 응답과 지역 코드·이름도 보존한다.
다른 코드의 동명역을 합치거나 TAGO 코드를 KRIC의 기관·노선·역 코드에 끼워 넣지 않는다.
TAGO는 좌표를 제공하지 않는다. 미제공 좌표는null이며 일반철도 자료에 좌표가 모두 생겼다고 주장하지 않는다.
KRIC 일반철도 웹 자료의 별도 주소·좌표 수집은 이번 구현 범위에 포함하지 않는다.

기존 `rail_reference_collection_job`에 독립 op를 추가한다. KRIC48시간 due와 별개로 TAGO의 첫 수집을
시작할 수 있고, TAGO도 성공 후48시간 보호를 유지한다. 기존 매일03:00 KST 예약과 native reference tag는 같다.
네트워크 중 DB 연결·catalog 잠금을 보유하지 않으며 SDK의 초당1회 요청 제한을 사용한다.
지역 최대100개·지역당 최대1000역·전국 최대10000역의 완결 수량과 중복·코드/이름 충돌을 확인한다.
부분 페이지·무자료 전국집합·25% 미만 급감·제공자 오류는 이전 승인 목록을 보존한다.

완료 후 짧은 저장 transaction에서 TAGO 역·`ReferenceExportState(rail-station,tago)`·native 실행 성공을
함께 commit한다. 실패하면 이 transaction을 되돌리고 TAGO scope의 실패만 기록한다. KRIC의 기존
`nationwide` head·역·수동 매핑은 변경하지 않는다. 원본/과거 행을 삭제하지 않으며 migration도 없다.
운영과 같은 소유권 세션의 합성 제공자 오류에서 `CollectionLeaseLost`와 running 잔여를 재현했다.
종료 상태를 ORM으로 변경해 fence가 종료 전 소유권을 확인하도록 고쳤다. 회수된 owner는 다음 지역 호출이나
source 실패 기록을 시작하지 않는다. 원 실패 원장은 Git 밖에 보존한다.

## Map 계약

기존 `/v1/service/exports/rail-stations`가 KRIC 필수 scope와 첫 성공 후의 TAGO scope를 함께 읽는다.
아직 TAGO 최초 성공이 없으면 기존 KRIC export는 유지한다. 승인된 TAGO가 있으면 source별 membership·
시각을 동일 RR에서 검증하고 합친 DTO를 고정한다. TAGO 실패는 이전 승인 목록+stale로 전달한다.
각 source의 코드를 보존하고, TAGO의 KRIC 코드 필드·code_active는 미연결 상태를 유지한다.
기존 필드·token/peer·cursor·15분 snapshot·완료 집합의 ETag·부분 응답 보호를 바꾸지 않는다.
Map 적재와 예약은 이 작업에서 변경하지 않는다.

## 검증과 실제 반영 상태

첫 WSL SQLite67개와 Python3.12/PostgreSQL18의 WSL·Docker87개씩을 통과했다. 서로 겹치는 시험은 합산하지 않는다.
소유권 세션의 실패/성공 정산과 회수 후 다음 지역 호출 차단을 포함한 최종11개도 Python3.12·PG18의
WSL/Docker에서 각각 통과했다. 실제 이미지·공식 최초 수집·Map peer의 전체 paging/요청4역 대조는
진행 중이다. 아직 일반철도 운영 수용 완료로 표시하지 않는다.

정본은 Git 밖 `transport-tago-stations-20261109/plan.json`이다. 기존 API·CS는 서로 다른 기반 소스와
의존성을 쓰므로 역할별 기반 이미지를 보존하고 변경된 source3파일만 같은 새 patch revision으로 반영한다.
전체 CS 소스가 API 소스와 같다고 해석하지 않는다. 웹·schema0041·키/환경·다른 서비스는 보존한다.
