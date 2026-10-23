# Map 담당 인계: 현재 상태·참조 service API

## 구현·운영 상태

Map PR1355의 기존 consumer는 T1의 `collection/has_more/next_cursor` 페이지를 읽는다.
새 T2/T3는 `meta/snapshot_id/snapshot_expires_at/total_count/items/has_more/next_cursor`의 별도
고정 집합 계약이다. 기존 T1 parser로 직접 읽지 말고 Map 쪽에 새 reader를 추가해야 한다.
기존 fuel/rest-area/T1 응답은 이 작업에서 변경하지 않았다.

| 구분 | 경로 suffix | Transport PR | 운영 상태 |
| --- | --- | --- | --- |
| T2 | highway-traffic/current | 114 | 머지됨, 새 API 미배포·flagOFF |
| T3 | bus-terminals | 115 | 머지됨, 새 API 미배포·flagOFF |
| T3 | ferry-ports | 116 | 머지됨, 새 API 미배포·flagOFF |
| T3 | rail-stations | 117 | 머지됨, 새 API 미배포·flagOFF |
| T2 | parking/current | 118 | 머지됨, 새 API 미배포·flagOFF |

[제품 검증·머지/운영 잔여 gate 정산](reports/2026-10-23-map-t2-t3-acceptance.md). KAC quota 복구 PR119도 운영 rollout 전에 포함한다.

모든 경로는 `/v1/service/exports/` 아래이며 기존 `X-Kor-Travel-Transport-Service-Token` header/peer 허용 규칙을 사용한다.
새 인증 방식이나 브라우저 토큰을 만들지 않는다. 배포 및 source flag 활성화는 운영 수집 run과
조율하는 별도 gate이며 본 문서의 fixture 응답을 운영 검증으로 해석하면 안 된다.

## 실제 fixture HTTP 응답

[HTTP 기록](examples/map-service-exports/http-summary.json)은 격리 PostgreSQL과 실제 TCP uvicorn에서
`limit=1`, gzip 요청으로 캡처한5종200 응답이다. source head `2f52aed`의 테스트용 집합이며
운영 개수·좌표·시각이 아니다. 문자열 cursor는 fixture 키로 서명했고 예시의 만료시각은 이미
지났을 수 있으므로 운영 요청에 재사용하면 안 된다.

- [구간별 교통 현재](examples/map-service-exports/highway-traffic-current.json)
- [주차장 현재](examples/map-service-exports/parking-current.json)
- [버스터미널](examples/map-service-exports/bus-terminals.json)
- [항구](examples/map-service-exports/ferry-ports.json)
- [철도역](examples/map-service-exports/rail-stations.json)

`meta.generated_at`은 응답 생성, `meta.source_collected_at`은 source 승인시각이며 parking은
승인집합의 가장 이른 원천 관측시각을 쓴다. source_status는 ok/stale이며 item_count는 페이지의
행수, total_count는 고정 집합 전체행수다. 메타 없는/급감미확인 첫집합은503으로 닫는다.
철도 코드의 선행0과 nullable code/coords, parking의 airport_anchor, 항구 guideline 좌표null을
그대로 보존한다. T1 fuel/rest-area 및 T3 참조의 admin은 현재 좌표의 coordinate_key와
reverse_address_entries가 일치할 때만 싣고, 없거나 불일치하면 null이다. 주소 provider는
vworld/kakao이며 nullable code/주소 필드를 보존한다. 검증된10자리 legal_dong_code를
직접 쓰고 geo를 재호출하지 않는다. 기존 Map T1 consumer의 admin 소비는 별도 후속이다.

T4는 [별도 가격 이력 계약](map-service-price-history.md)을 따른다. query는 product/from/to,
limit은 전체 페이지 행수, cursor revision/만료는409다. 위 T2/T3의410과 혼동하지 않는다.
휴게소 가격 이력은501이며 이력 표를 새로 만들지 않는다. Map의 기존 T4 query/parser와
producer 응답 사이 호환 수정은 Map 소유 후속이다.

## Map reader 처리 순서

1. 같은 token/peer로 첫 페이지를 요청하고 gzip을 해제한다. limit은1~5000이며 작업 동안 고정한다.
2. `items`를 작업용 새 집합에 누적한다. 응답의 서명된 next_cursor를 수정하거나 다른 endpoint·limit에
   재사용하지 않는다. snapshot_id와 total_count가 모든 페이지에서 동일한지 확인한다.
3. has_more=false까지 모두 수신하고 누적수량·고유identity를 확인한 뒤 Map의 성공집합을 교체한다.
   부분수신·503·미확인 원천빈응답을 근거로 기존 Map집합을 닫지 않는다. stale은 이전확인집합+상태로 표시한다.
   단, highway-traffic/current의 승인head가 권위정상0을 확정한200(total_count=0/items=[]/
   has_more=false/next_cursor=null)은 유효한 빈 완결집합이다. 이 응답을 무조건 거부하지 않는다.
   참조/parking의 미확인 빈 집합은 서버가503으로 닫는다.
4. 410은 고정snapshot15분TTL 만료다. 작업용 누적값을 버리고 cursor 없이 첫 페이지부터 새로 받는다.
   422는 잘못된/다른scope cursor·limit이며 같은 방식으로 재시작한다. 재시도 횟수와 지연은 Map에서 유한하게 둔다.
5. ETag는 응답페이지의 validator다. 완료한 이전집합의 첫페이지 ETag만 같은 endpoint·limit 요청의
   If-None-Match로 사용한다. 304이면 이미 완결된 Map집합을 유지한다. 미완료 작업이나 다른limit의
   ETag를 완결 성공으로 재사용하지 않는다. TTL이 지났거나 source상태가 달라지면200/410을 처리한다.
6. source가 다음 수집으로 바뀌어도 기존cursor는 최초 DTO를 만료까지 읽는다. 새 조회의 snapshot_id가
   바뀌었다고 중간의 기존페이지를 섞지 않는다. Map 데이터 반영은 완결집합 단위로 한다.

## 배포 및 초기 승인

API 이미지와 collector code 모두 새 코드를 사용해야 한다. migration0030~0033을 현재 head까지
적용한다. `TRANSPORT_MAP_CURRENT_ENABLED` 하나가 새 T2/T3 API와 collector 모두를 제어하며
source별 개별 flag가 아니다. 기본값은 false이고 API·CS 환경을 일치시켜야 한다. 활성화 뒤
승인된 정상수집 순서로 scope별 head를 채운다. 이력 전체 backfill은 하지 않는다.
BUS express/intercity, KAC/ICN처럼 설정에 활성인 source의 head가 모두 준비되기 전에는503이다.
API가 먼저 flagON되어도 미승인·구버전 행을 추정해 export하지 않는다.

공유 daemon은 RUNNING을 유지하고 Transport instigator만 현재 배포런북에 따라 관리한다.
정상 source 수집·서버간 token/peer·새 API 최초snapshot/전체페이지/304/410/stale을 배포 후 별도로
확인한 뒤 Map reader를 활성화한다. 운영 배포·source 실호출은 root가 조율한다.
