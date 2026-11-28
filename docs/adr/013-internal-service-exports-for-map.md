# ADR-013: kor-travel-map에 OpiNet·KREX·공항 데이터를 토큰으로 닫힌 내부 export로 제공한다

- **상태**: accepted
- **날짜**: 2026-10-02
- **결정자**: agent + human
- **보완**: [ADR-005](005-versioned-rest-api-contract.md)가 미뤘던 "외부 소비자 인증"과
  "`docs/openapi.json` 최신 여부 CI 게이트"를 이 범위에서 처음 정한다.
- **개정**: 2026-10-23(참조 데이터는 마지막 성공의 나이로 판정, T4 추가), 2026-11-24(돌발 0건 실패, 503 사유 `code`·일시 DB
  불가 503, T1 전송), 2026-11-27(`rest-area-food`). 각 개정은 아래 같은 이름의 절에 원칙만 두고, 값·분기·이력은
  → 세부: [service export 생산자 운영 계약](../architecture/service-exports.md)

### 컨텍스트

kor-travel-map(Map)은 OpiNet 주유소·유가, 한국도로공사(KREX) 휴게소·휴게소 유가·돌발, 공항 메타데이터를 provider 라이브러리로
직접 받아 왔다. transport도 같은 원천을 이미 수집하거나(오피넷 전국 주유소 약 1.2만 곳, 5분 돌발) 수집할 수 있는 테이블을 갖고
있었다(휴게소). 같은 원천을 두 서비스가 따로 호출하면 data.go.kr/OpiNet 일일 한도를 나눠 쓰고, 결과가 서로 어긋난다.
소유자 결정(2026-10-02): **Map에서 transport로 얻을 수 있는 것은 transport API로 바꾸고, 필요하면 transport API를 고친다.**
OpiNet은 transport의 브라우저 수집본을 정본으로 쓴다.

기존 공개 지도 API(`/v1/transport/features/places` 등)는 marker 표시용이라 limit·균등 배분이 있고 provider 원본을 숨기며,
돌발은 "최근 24시간"이라 "지금 활성인 집합"을 표현하지 못한다.

### 결정

1. **내부 export 표면**을 공개 API와 따로 둔다: `/v1/service/exports/` 아래의 **T1 현재/참조 집합**(주유소·휴게소·휴게소 유가·
   돌발 활성·공항, 2026-11-27부터 휴게소 먹거리). 모양은 kor-travel-concierge export와 같은 무-envelope cursor 페이지에 근거 수집
   상태(`collection`)를 붙이고, 각 item은 안정 자연키와 원본 provider 행을 담는다. 같은 경로 아래의 T2/T3 고정 snapshot과 T4 가격
   이력은 인증(결정 2)만 공유하고 응답 계약은 각자의 문서가 정한다.
   → 세부: [service-exports §1](../architecture/service-exports.md#1-표면과-인증-adr-013-결정-12)
2. **인증은 서비스 토큰 그리고 네트워크 주소 allowlist 둘 다다.** 토큰은 backend가 언제나 검사하고, 주소 allowlist는 소비자를 마주한
   경계에서 검사한다 — backend의 peer 주소 allowlist(기본 loopback), 그리고 Odroid 운영에서는 소비자 앞의 API gateway export
   location이 CIDR allowlist로 받는다(gateway가 loopback으로 backend에 넘기고 클라이언트 XFF는 지운다). 토큰이나 backend peer가
   어긋나면 404로 경로를 숨긴다(gateway CIDR 거부는 403). 호출자가 정하는 `Host` 헤더는 쓰지 않는다. 공개 웹 프록시는 이 경로를 전달하지 않는다.
   → 세부: [service-exports §1](../architecture/service-exports.md#1-표면과-인증-adr-013-결정-12)
3. **현재 집합 의미와 신선도 계약(T1 모든 dataset 공통)**: 200 응답의 `items`는 "마지막 성공 수집의 현재 집합"이다 — 소비자는 거기
   없는 행을 사라진 것으로 다뤄도 된다. 그래서 **그 집합을 증명할 수 없으면 200을 주지 않고 503**이다.
   - 근거 수집의 이력이 없거나(수집이 꺼진 dataset 포함) 마지막 성공이 dataset별 stale 기준을 넘으면 503이다.
   - **참조 데이터**(주유소·휴게소·휴게소 유가·휴게소 먹거리)는 마지막 **성공**의 나이로 판정한다 — 기준 안이면 그 뒤 시도가
     실패했어도 마지막 성공 집합을 200으로 낸다(실패한 시도는 저장 transaction을 되돌려 집합을 바꾸지 않는다). 마지막 시도의
     실패는 가산 필드로만 알린다(2026-10-23 개정). 일부 지역 실패 한 번으로 행이 사라지지 않도록 마지막 성공 전 일정 기간
     재관측된 행까지 현재 집합으로 낸다(`rest-area-food`만 예외 — 2026-11-27 개정).
   - **돌발 활성 집합**은 "지금"의 집합이라 마지막 **시도**가 실패했거나 짧은 기준을 넘으면 503이고, 전국 0건은 성공이 아니라
     상류 이상으로 본다(2026-11-24 개정). 페이지 없이 마지막 성공 수집이 본 사건 전체를 한 번에 낸다.
   - 200 본문의 `failed`·`stale`은 503 사유라 200이면 언제나 false다. 상태와 데이터는 한 요청 안에서 한 snapshot으로 읽고,
     페이지는 요청마다 따로 판정한다(페이지 중 503이면 소비자는 그 run 전체를 실패로 다룬다).
   - 503은 기계 판독 사유 `code`와 `Retry-After` 힌트를 싣고, export 경로의 일시 DB 불가·준비 상한 초과도 500이 아니라 503이다
     (2026-11-24 개정). `code`의 뜻이 계약이고 `Retry-After` 값은 힌트다.
   → 세부(stale 기준 값·재관측 여유·code 분기): [service-exports §2~§7](../architecture/service-exports.md#2-현재-집합과-신선도-adr-013-결정-3),
   [Map 인계 "503 사유 code"](../map-service-exports-handoff.md#503-사유-code와-retry-after-2026-11-24)
4. **새 수집**: 휴게소 기준정보(data.go.kr)와 휴게소 주유소 현재 유가(EX)를 transport가 수집·적재한다. 두 원천은 전국 집합이므로
   0건 수집은 실패다. 원천에 안정 ID가 없어 휴게소 자연키는 Map이 쓰던 이름·노선·방향 규칙을 따른다. 기본 비활성이다.
   → 세부: [service-exports §6](../architecture/service-exports.md#6-휴게소-계열-수집-adr-013-결정-4)
5. **공항**은 주차 수집 여부와 무관하게 `python-krairport-api` 번들의 운영 공항 전체를 내고, 주차 데이터 보유 여부를 표시한다.
   → 세부: [service-exports §1](../architecture/service-exports.md#1-표면과-인증-adr-013-결정-12)
6. **계약 정본**은 `docs/openapi.json`이고 CI가 `scripts/export_openapi.py --check`로 최신 여부를 검사한다(transport 자신의 drift 방지).
   이 export는 Map을 위해 있다 — Map에 필드·모양이 필요하면 이 API를 그에 맞게 바꾼다(같은 PR 쌍, 버전·호환 층·옛 모양 shim
   없음). Map은 이 파일을 pin·vendoring하지 않고 응답을 런타임에 엄격히 검증한다(2026-10-03 소유자 결정, Map ADR-106).

### 개정 2026-10-23 — 참조 데이터는 마지막 성공의 나이로 판정한다

옛 결정 3의 "마지막 수집이 실패했으면 503"이 저장 집합이 멀쩡한데도 Map 적재를 끊었다. 참조 데이터는 마지막 성공이 stale 기준
안이면 200이고, 마지막 시도 실패는 `collection.last_attempt_failed`로 알린다. 돌발은 바꾸지 않는다. 공개 지도 API의 신선도 표시는
의도적으로 다르다. 같은 날 소유자 결정으로 유가 수집의 다음 예정을 수집 **시작** 기준 8시간으로 바꿔 8시간 tick을 건너뛰지 않게 했다.
**오피넷 호출은 하루 3회(8시간 tick)로 소유자가 제한한 주기이며, 이를 넘는 추가 run(예: 경보 재시도)은 이 ADR 개정과 소유자 승인이
필요하다.** → 세부: [service-exports §3·§4](../architecture/service-exports.md#3-참조-데이터는-마지막-성공의-나이로-판정한다-2026-10-23-개정)

### 개정 2026-11-24 — 돌발 활성 집합의 0건은 성공이 아니다

전국 활성 돌발 0건은 상류 이상으로 보고, 다시 조회해도 비면 실패로 기록해 마지막 성공 집합을 유지한다(export 503). 옛
"빈 목록은 현재 돌발 없음" 해석은 이 개정으로 바뀐다(INCIDENT-EMPTY-SET-20261124).
→ 세부: [service-exports §5](../architecture/service-exports.md#5-돌발-활성-집합의-0건-2026-11-24-개정-incident-empty-set-20261124)

### 개정 2026-11-27 — 휴게소 먹거리 `rest-area-food`(KREX 0615·0502)

Map ADR-127을 위해 T1 export 하나를 더한다. 두 원천을 한 transaction으로 저장하고 0건·급감·건수 불일치는 실패다. 이 dataset만
재관측 여유 없이 마지막 성공 수집이 본 행 그대로를 낸다(원천에서 내려간 메뉴가 Map에 남지 않게).
→ 세부: [service-exports §6](../architecture/service-exports.md#휴게소-먹거리-rest-area-food-2026-11-27-krex-06150502),
[Map 인계](../map-service-exports-handoff.md#휴게소-먹거리-t1-rest-area-food-2026-11-27)

### 개정 2026-11-24 — 503 사유 `code`·`Retry-After`, 일시 DB 불가 503, 유가 export 유예(정책 변경 포함)

Map 호출 감사의 생산자 쪽 변경이다. export 503은 가산 `code`와 `Retry-After`를 싣고, export 경로의 일시 DB 불가·snapshot 문장
상한은 500 대신 503이며(공개·관리 경로는 그대로), T2/T3 잠금 경합은 한 번 예산 안에서 다시 시도하고, 유가 export 유예를 수집
상한만큼 늘린다. 결정 3의 현재 집합 의미와 돌발 정책은 바꾸지 않는다.
→ 세부: [service-exports §4·§7](../architecture/service-exports.md#7-503-실패-계약의-생산자-쪽-세부-2026-11-24-개정),
[Map 인계 "503 사유 code"](../map-service-exports-handoff.md#503-사유-code와-retry-after-2026-11-24),
배포 보류(2026-11-25 해제)는 [배포 런북](../runbooks/deployment.md#배포-보류해제됨-export-503-상태-코드-변경2026-11-24-pr-277)

### 근거

- 공개 marker API를 넓히는 대신 별도 표면을 둔 것은 둘의 계약이 다르기 때문이다. marker는 limit·bbox·표시 필드가 핵심이고,
  export는 전량·안정 키·원본 증거·"현재 집합" 의미가 핵심이다. 하나로 합치면 공개 응답에 provider 원본을 내거나 export에 표시용
  절단이 섞인다.
- 토큰만으로도 닫히지만 주소 allowlist를 더하면 토큰이 새도 허용 대역 밖에서 원본 대량 조회가 불가능하다. 결정 당시 Map은 같은
  호스트의 host-network 컨테이너에서 `127.0.0.1:14001`로 불렀다. 2026-10-19부터 Odroid 운영에서는 Map(n150)이 API gateway의 export
  location을 거쳐 오므로 backend가 보는 peer는 loopback이고, 실제 네트워크 경계는 gateway CIDR allowlist + 토큰이다
  ([ADR-014](014-odroid-host-and-deploy-host-flag.md) 결정 4).
- 신선도를 플래그로만 알리고 200을 주는 대안은 버렸다. 소비자마다 플래그를 읽는 코드를 따로 지켜야 하고, 한 곳이라도 빠지면
  빈·낡은 집합이 삭제·종료로 번진다. 503은 읽지 않으면 실패하는 쪽으로 기본값이 안전하다(Map은 플래그도 다시 확인한다 — Map ADR-106).
- 참조 데이터를 마지막 성공의 나이로 판정하는 것은 이 원칙의 범위 안이다 — 실패한 시도가 집합을 바꾸지 않으므로 그 집합은
  여전히 "마지막 성공 수집의 현재 집합"으로 증명된다.
- 돌발 활성 집합을 페이지로 나누지 않는 것은 수백 건 규모이고, 페이지 사이에 수집이 끼면 집합이 섞여 종료 판단이 틀어지기 때문이다.

### 결과 (긍정)

- 같은 원천을 한 번만 호출한다. Map은 OpiNet·KREX·krairport 의존과 키를 걷어낼 수 있다.
- 휴게소 기준정보·유가가 transport 지도에도 쓰일 수 있는 상태가 된다(`features/places?kind=rest_area`).
- `docs/openapi.json`이 처음으로 CI가 지키는 정본이 된다.

### 결과 (부정)

- Map의 해당 데이터가 transport 가용성에 묶인다. transport가 멈추면 Map 적재가 실패한다(오래된 값을 새 값처럼 적재하지는 않는다).
- 토큰 하나가 export 전체 권한이다(읽기 전용). 범위별 토큰은 소비자가 둘 이상이 될 때 다시 본다.
- OpiNet 정본이 브라우저 수집(`opinet.experimental`)이라 공식 API보다 원천 변화에 약하다.

## 2026-10-23 추가: 요청 시 프록시하는 가격 이력(T4)

현재/참조 집합 계약의 예외로, 주유소 가격은 기존 이력 표에서 주유소·기간을 제한해 읽는 service API를 둔다. Map은 요청 시
프록시하고 저장하지 않는다. 인증은 결정 2와 같고 새 이력 표를 만들지 않는다(휴게소 이력은 501).
→ 세부: [가격 이력 계약](../map-service-price-history.md)

## 개정 2026-11-24 (T1 전송)

T1의 전송 방식(gzip 협상·int4 밖 cursor 422·snapshot 상한 초과 503 + `Retry-After`·끊긴 요청)을 바꾼다. JSON 본문과 결정 3의
현재 집합 의미, 200/503 판정은 바꾸지 않는다.
→ 세부: [service-exports §8](../architecture/service-exports.md#8-t1-전송-2026-11-24-개정),
[성능 기준](../architecture/performance.md#map-t1-export-본문-구성과-연결-반납-2026-11-24)
