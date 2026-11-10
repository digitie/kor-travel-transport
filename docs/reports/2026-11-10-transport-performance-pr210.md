# Weather PR210을 참고한 Transport 조회 개선

## 범위와 현재 상태

사용자는 Weather PR210을 참고해 Transport 속도 개선을 요청했다.
[Weather PR210](https://github.com/digitie/kor-travel-weather/pull/210)은 닫힌 미병합 문서 PR이며,
완료된 제품 구현으로 취급하지 않는다. 실제 사용 중인 Map 기준정보의 반복 export와
도시철도 카탈로그 조회를 측정하고, 상태·본문·cursor의 수명을 구분하는 제안을 적용한다.
집중 검증·새 API/수집기 이미지·운영 HTTP·원 일정 복원·Manager·부모 실제 종료를 완료했다.
[Draft PR178](https://github.com/digitie/kor-travel-transport/pull/178)은 PR177 위의 후속이며 main 병합은 하지 않았다.

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
웹·SDK·의존성은 변경하지 않아 재빌드하지 않았다.

## 실제 이미지 반영과 HTTP 수용

제품d0c9010의 새 API `5bee4f97`/CID `d0c79634`, 수집기 `37f45393`/CID `ada0fe6e`를 반영했다.
PG18.6/schema0041·12302/12306 명령·SDK18864a3·Settings·개별 환경/키·마운트·자원을 보존했다.
API 먼저 반영 후 기존 수집/worker의 자연 종료를 확인해 수집기를 교체했다. 기존20일정은 원상태로
복원됐고 다섯 역할 healthy·Transport location·Manager adopt/verify/show healthy를 확인했다.
frontend·관리자·gateway와 Weather/공용 daemon·다른 서비스, 환경 파일은 그대로다.
DB migration·추가 외부 수집·백업/복원·원본/영구 통계 정리·자동 rollback은 실행하지 않았다.

| 경로 | 전 | 후 | 실제 결과 |
| --- | --- | --- | --- |
| 도시철도 카탈로그 | 4.071초 | 2.442초 | 1108역, 전체 항목 SHA 동일 |
| 철도 기준정보 첫 페이지 | 10.027초 | 12.426초 | 새 본문 구성, 첫1000건/전체1466건 |
| 같은 ETag 조건부 요청 | 4.624초 | 1.807초 | HTTP304 |
| 철도 두 번째 페이지 | 미측정 | 0.475초 | 같은 snapshot, 나머지466건 |

1466건의 자연키 중복0·두 페이지 완결·source_status=ok와 API/gateway health200,
토큰 없음/오류404를 확인했다. 카탈로그의 실제 전체 항목 SHA는
`1a8ebf743790afa4563fa8cf3b42bda164351b825525a4dde9b3c35917c9c235`로 기존 국소 대조와 일치한다.
운영 첫 요청과 조건부 요청을 한 번씩 읽었으며 별도 warm·캐시 삭제·수집을 추가하지 않았다.

전후 부하·새 snapshot 생성 여부·수집기 기동 상태가 다르므로 코드 단독 개선율이나 p95가 아니다.
특히 **최초 전체 본문은12.426초로 개선되지 않았다.** 입력 지문 확인 외에도 전체 DTO·JSON·
snapshot insert와 페이지 DTO/ETag 구성 비용이 남는다. 모든 최대 응답1초 목표 달성으로 쓰지 않는다.
기존 대량 유가 조회나 PC/모바일 렌더링을 새로 측정한 결과도 아니다.

빌드 first `4954de0b5114435c8e4b1e42c19f434f`는 실제0·자식11개 종료,
배포 first `dc5ec6571e7d4fccbbfec3b8a8af48f9`는 실제0·자식84개 종료다.
두 최초 Invocation의 done·Main0·cgroup부재·소유 PID부재를 별도 읽기로 검산했다.
정본은 Git 밖 `transport-performance-pr210-20261110/final-acceptance.json`,
SHA `1be4af369bf44ca1e8433a3307086df66a1bca8dd83fe88d3337099118f69d9d`다.

[제품 CI42727647602](https://github.com/digitie/kor-travel-transport/actions/runs/42727647602)는
최종 관측에서 frontend/관리자 성공·migration/Alembic/OpenAPI 검사 성공, backend 전체 pytest는 진행 중이었다.
live-e2e는 생략이며 실제 HTTP·집중 WSL/Docker 검증과 구분한다. 문서 정산 커밋은 제품 tree를
변경하지 않고 추가 전체 CI를 요청하지 않는다. 기존 제품 CI는 중단하거나 재실행하지 않는다.
