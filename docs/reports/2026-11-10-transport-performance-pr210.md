# Weather PR210을 참고한 Transport 조회 개선

## 범위와 현재 상태

사용자는 Weather PR210을 참고해 Transport 속도 개선을 요청했다.
[Weather PR210](https://github.com/digitie/kor-travel-weather/pull/210)은 닫힌 미병합 문서 PR이며,
완료된 제품 구현으로 취급하지 않는다. 실제 사용 중인 Map 기준정보의 반복 export와
도시철도 카탈로그 조회를 측정하고, 상태·본문·cursor의 수명을 구분하는 제안을 적용한다.
현재 후보는 집중 검증을 마쳤으며 이 문서 작성 시 운영 이미지 교체는 아직 하지 않았다.

기존 운영은 제품4dac82d의 API b9ac0d18·수집기22f47ac5·PG18.6/schema0041이다.
이 작업은 SDK·웹·의존성·Alembic·신규 상태 TTL을 변경하지 않는다.
수집·원본·영구 통계·다른 서비스·기존 토큰 경계는 보존한다.

## 실제 병목과 기준 측정

같은 운영 API의 첫 요청과 조건부 요청을 관측했다. 캐시를 지우거나 수집을 추가하지 않았다.

| 경로 | 단일 관측 | 비고 |
| --- | --- | --- |
| 도시철도 카탈로그 | 4.071초 | 1108역, HTTP200 |
| 철도 기준정보 첫 페이지 | 10.027초 | 1466건 집합의 첫1000건, HTTP200 |
| 같은 ETag 조건부 요청 | 4.624초 | HTTP304이나 원천 전체 DTO 재구성 |

정본은 Git 밖 `transport-performance-pr210-20261110/baseline-http-r2.json`이다.
원 첫 시도의 export404는 인증 헤더 선택 오류로 별도 보존하며 성능 근거로 쓰지 않는다.
이는 단일 표본이며 OS 냉기동·부하 p95·전국 보장·코드 단독 개선율이 아니다.

운영 DB의 같은 읽기 전용 RR에서 수행한 두 번의 국소 대조는 다음과 같다.

| 작업 | SQL | wall | 프로세스 CPU |
| --- | --- | --- | --- |
| 전체 철도 source DTO·주소·연결·해시 구성 | 13 | 4.636 / 3.822초 | 2.045 / 1.382초 |
| DB 입력 지문 | 1 | 2.963 / 0.476초 | 0.125 / 0.054초 |

전체 구성은1466항목·canonical bytes1428193이며 두 결과 SHA가 같다.
입력 지문은 본문 해시와 다른 목적이므로 서로 같은 값이라고 주장하지 않는다.
정본 `native-readonly-profile-r3.json`은 별도 Python 프로세스에서 후보를 메모리에만 적재했고
운영 앱 파일·데이터·수집·lifespan을 변경하지 않았다. 초기 함수 탐색 실패 두 건도 보존한다.

## 입력 지문으로 완료 본문 재사용

기존 첫 페이지는 source 전체를 구성한 뒤에야 같은 snapshot인지 확인했다.
후보는 같은 RR에서 head·실제 source 값·주소·저장 매핑의 입력 지문을 먼저 읽는다.
같은 release와 입력에 이미 완료한 snapshot이 있으면 source DTO·주소 파싱·전체 JSON 해시를
다시 만들지 않는다. DB 통계·수정 시각·xmin을 변경 감지의 대체물로 사용하지 않는다.

- source의 실제 typed 값, rail active code·registry, 주소의 실제 payload·좌표키·상태·해석 시각을 포함한다.
- bus/ferry 수동 위치 revision을 포함하며 사용하지 않는 원본 raw와 주소 checked_at·실패 횟수만 제외한다.
- UTC 날짜와 float 원래 비트를 사용해 세션 시간대와 음수0의 차이를 구분한다.
- release revision을 포함해 라이브러리·파싱 정책 변경 시 같은 본문을 잘못 재사용하지 않는다.
- head 실패·신선도는 매 요청 실제 DB에서 판정한다. Weather의 승인된60초 지연을 Transport에 옮기지 않는다.
- PostgreSQL이 아니거나 release가 미정이면 기존 전체 구성 경로를 유지한다.

입력 지문은 기존 선택 membership 안의 작은 typed 관계에 한정한다. raw 이력 전체 스캔·
MV refresh·새 전역 잠금·writer 직렬화·검증 생략은 추가하지 않는다. 여전히 O(N) 입력 확인 비용이
있으며 완전한 최초 miss는 기존 상한 안에서 전체 본문을 구성해야 한다.

## Cursor와 동시성

15분 epoch가 바뀌었고 같은 입력의 이전 snapshot이 남아 있으면 DB 안에서 불변 항목을
새 handle로 복사한다. 이전 handle 만료를 연장하지 않는다. 새 handle에는 기존 방식대로
최소15분의 수명을 주고 원래 source 시각을 보존한다. 복사 전에 수량·ordinal을 검산하고,
새 부모/항목을 같은 transaction으로 저장한 뒤에만 만료 정리를 수행한다.

유효한 이전 cursor와 새 cursor는 각자의 snapshot을 읽는다. 완성 항목이 없거나 순서가 깨지면
503이며 성공 본문을 추정하지 않는다. 동시 최초 생성은 기존 unique 제약·RR 재시도로 처리한다.
새 application cache 잠금은 없다. 실제 source 변경은 다음 RR 요청에 반영하고, 이미 시작한
reader는 일관된 이전 view를 읽는다. 기존 SQL10초·lock2초·구성15초·크기 상한은 유지한다.

## 철도 카탈로그 후보와 검증 경계

카탈로그는 전체 ORM 두 객체 대신 응답 필드만 Core 투영하고 동일 DTO·provider 편의정보
파서를 사용한다. 운영1108역의 item-only710821bytes/SHA가 기존 경로와 일치했다.
초기 교대 측정은 개선과 악화가 섞였다. 후속에서는 각 단계 전에 GC를 정리하고
기존→Core→Core→기존을 세 번 반복했다. 총12회 결과의 해시가 모두 같았고,
기존 CPU680~721ms 대비 Core423~500ms였다. wall은 기존1.460~3.015초,
Core0.848~2.407초로 편차가 남는다. 원장 `native-catalog-controlled.json`으로
객체 구성 비용 감소를 확인해 채택하되 운영 p95·코드 단독 HTTP 개선율로 쓰지 않는다.

첫 WSL PG18 회귀는65통과·1실패였다. 실패는 새 내부 keyword를 받지 못한 테스트 계측 wrapper이며
그 원문을 보존한 뒤 전달 인자를 보정했다. 추가 WSL20통과·1실패의 마지막 실패는 JSONB 응답의
음수0 정규화를 고려하지 않은 기대값이었다. 원천 double 비트와 새 snapshot/ETag를 검증하도록
기대값만 보정한 해당1개가 WSL에서 통과했다. Docker PG18은 집중21개가 모두 통과했다.
겹치는 시험을 합산하지 않는다. Docker 경고1개는 읽기 전용 checkout의 pytest cache 쓰기다.
각 전용 PG의 정확 CID·이름·소유 label을 확인해 종료·제거했고 기존 SDK 환경을 재사용했다.

주소·수동 위치·signed zero·동시 writer·상태 즉시 반영·snapshot 만료/복사와 네 종류 reference의
재사용/변경 감지를 검증했다. 문법·미정의 이름·새 모듈의 미사용 import와 diff 검사도 확인했다.
새 이미지·운영 HTTP는 다음 실제 반영 단계에서 정산한다. 웹·SDK·의존성은 변경하지 않아 재빌드하지 않는다.
