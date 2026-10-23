# Map T3 항구 참조 export

`GET /v1/service/exports/ferry-ports`는 기존 service 인증·peer 검사·공통meta·고정DTO
snapshot/cursor/TTL/gzip/ETag를 사용한다. Bus와 source projection만 다르게 하여
같은 bounded engine을 공유한다. 기존 bus operationId/필드/cursor는 유지한다.
새 migration 없이 PR115 schema0032를 사용하며 기본OFF다. 운영 적용은 하지 않았다.

## Source 성공 범위

항구 목록과 KOMSA 좌표 보충의 성공은 별개다. provider public
`DataGoKrMaritimeClient.iter_ports(page_size=100,max_pages=20)`의 정상종료를 사용한다.
고정 SDK는 항구 목록에서 total 누락을 거부하고 고정total/전체수량/고유ID/중간빈page/
호출상한을 검증한다. terminal/ship-type의 단일응답 허용 규칙을 항구에 적용하지 않는다. Transport는
HTTP/원문파싱/다음page 호출을 다시 구현하지 않는다. public wire receipt가 없으므로
proof에 `wire_total_receipt=false`를 남겨 원문total 증명으로 오인하지 않게 한다.

nonempty·이름/코드·고유ID·최대2000개를 추가검증하고 빈/잘못된 목록은 최대1회 재확인한다.
이전 성공25% 미만은 다시fetch해 회복되면 사용한다. 여전히 급감하면 권위total receipt가
없으므로 이전집합을 보존한다. 최종 저장 직전에 최근 성공head의 denominator도 확인한다.

좌표 보충 예약/lookup receipt commit은 항구 reference 쓰기 전에 끝낸다. reference rows,
source head/membership/native terminal은 마지막transaction에서 함께 확정한다. 좌표 실패/
유예로 native run이partial_success여도 core 항구목록은 정상일 수 있다. proof에 별도좌표
확인/유예 수량을 남긴다. 옛worker의 실패는 DB조건부 UPDATE로 최신성공을 덮지 못한다.
rollback 뒤 native scalar ID만 사용한다.

## DTO와 보존

source+port_id natural_key, 이름/코드/좌표/location_source/location_point_count/
manual_location_revision/T1 admin을 제공한다. legacy guideline 한 점을 승선항구로 쓰지
않으며 guideline/유효범위 밖 좌표는null/admin=null/point_count0이다. unknown을0,0으로
바꾸지 않는다. 수동좌표/파생주소 변경은 다음첫snapshot DTO에 반영하고 이전페이지는 고정한다.
source row.last_seen_at은 승인head.confirmed_at과 같아야 하며 flagOFF 미승인참조는503이다.

실패 또는9일 초과는 이전 성공+stale, 초도head없음은503이다. 최대20,000개/16MiB·400행
batch·15분TTL·unique admission·새RR최대1회재시도를 공유한다. partition 경계15초 검사와
개별statement10초이며 요청전체hard15초는 아니다. 이전cursor와 DTO는 만료까지 보존한다.

## 검증 상태

PR116 두 독립 리뷰·정확 CI PG1066 PASS/2 SKIP, 집중 PG42 PASS와 실제 TCP 결과는
[수용 정산](reports/2026-10-23-map-t2-t3-acceptance.md)에 기록했다. 운영 미배포/defaultOFF이며
실제 source bootstrap·Map consumer UI·ARM CPU/RAM 실측은 남았다.
