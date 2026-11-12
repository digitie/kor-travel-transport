# Map 철도·해운 기준정보 운영 활성화

## 요청과 실제 변경

사용자가 Map의 기차역·여객터미널 적재를 위해 Transport 운영 플래그와 기준정보 수집 활성화를 요청했다.
2026-11-09 API·수집기의 `TRANSPORT_MAP_CURRENT_ENABLED`를 true로 맞췄다.
`RAIL_REFERENCE_COLLECTION_ENABLED`·`MARITIME_REFERENCE_COLLECTION_ENABLED`와 해당 예약은 이미
활성 상태여서 그대로 유지했다. 이 공통 플래그는 철도·항구뿐 아니라 새 T2/T3 경로 전체에 적용된다.
이번 실제 source 수용 범위는 `rail-stations`·`ferry-ports`다.

정상 Manager G→Transport R/FD9에서 기존 수집의 자연 종료와 worker 부재를 확인한 뒤 같은 이미지를
재사용해 API·수집기만 재생성했다. 원20개 예약·센서 상태 복원, 두 역할 healthy와 native Settings,
Manager adopt/verify/show를 확인했다. 소스·이미지 빌드·DB schema0041·다른 환경·키·다른 서비스는 보존했다.
백업·복원은 사용자 지시에 따라 생략했고 원본 삭제·prune는 실행하지 않았다.

| 역할 | 소스 | 이미지 접두사 | 실제 새 CID 접두사 |
| --- | --- | --- | --- |
| API, 포트12302 | a3fbb4e9 | 857b507b | fb5a325b |
| 수집기, 포트12306 | a8869693 | 11418aa1 | 608e9326 |

API의 RustFS 미설정은 비수집 역할의 기존 설정이며 바꾸지 않았다. 실제 수집기는 RustFS가 설정돼 있다.
Manager current는 같은 이미지 집합의 기존 release를 채택했고 새 release 경로를 임의로 만들지 않았다.

## 공식 최초 수집과 소비자 확인

기존 동일 job의 활성·대기 부재를 확인한 뒤 native tag를 보존해 아래 작업을 각각 한 번 제출했다.
제출 부모의 종료와 수집 자체의 성공을 구분한다. Map 적재·Map 주간 예약은 변경하지 않았다.

| 작업 | Dagster run | 현재 확인 |
| --- | --- | --- |
| 철도 기준정보 | 8a2b70f8-77c3-4abb-9e42-c265160aa035 | SUCCESS, 앱8560·승인 집합1108건 |
| 해운 기준정보 | 517982ff-3b46-4b20-bdd4-6c8df3ba10f3 | 기준정보 앱8562 success·승인 집합753건, 후속 위치 보충 실행 중 |

실제 Map 수집기 호스트 n150에서 기존 service token·실제 peer로 GET했다. 철도는 같은
`snapshot_id`의1000+108건, 고유 natural key1108개·이름·완결 수량, source_status=ok와
완료 집합의 첫 페이지 ETag 재요청304를 확인했다. 좌표 null13건을 추정 보충하지 않았다.
해운 최초 관측503은 수집 중 head 부재로 보존했다. 기준정보 성공 뒤 별도 관측에서753건의
고유identity·완결200·source_status=ok·ETag304를 확인했다. 항구 좌표null611건을 보존한다.
공식 해운 job에는 기준정보 commit 이후 별도 위치 보충이 있으므로, 기준정보 성공과 전체job 종료를 구분한다.

## 정산과 남은 경계

활성화 부모의 첫 Invocation `db0a35934caa4ba2add5fdf42d54bcba`와 제출 부모
`b1023c12f2674a43a01c1859d400a805`는 실제 done0·Main0·cgroup 부재·소유 자식 종료다.
직접 Manager 모듈 호출의 compose 경로 실패는 원문을 보존했다. 정본 환경을 설정하는 공식
`ktdctl` 별칭으로 읽기·운영 검증을 통과했으며 Manager 미준비로 오판하지 않았다.

정본은 Git 밖 `transport-map-reference-enable-20261109/plan.json`과 활성화/제출의
`last-status.json`, `references-last-read.json`, `map-export-acceptance.json`이다.
토큰·키·DSN·원 URL/query·원본 응답은 문서나 Git에 넣지 않는다.

철도는 매일03:00 KST due 평가와48시간 성공 보호를, 해운은 기존 `0 3 */3 * *` 예약을 유지한다.
Map은 새 T3 완결 집합 parser로 읽고 전체 paging/identity 검산 뒤에만 적재 집합을 교체한다.
부분 응답이나503으로 기존 Map 집합을 지우지 않는다. Map 적재1회와 주간 예약 활성화는 Map 담당 후속이다.
