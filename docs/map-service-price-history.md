# Map service 가격 이력 API(T4)

상태 갱신(2026-10-24): T4는 PR110에서 구현·머지했고 T1/T5와 함께 e01f8e9 API·CS에 배포됐다. [배포·원천 미완 기록](reports/2026-10-23-map-exports-deployment.md)을 따른다. producer 정상 계약과 Map의 기존 가격 이력 parser/query 호환 수정·소비자 수용은 별개다. 아래 검증 중 표현은 최초 PR 당시 기록이다. 기존 이력·통계·대시보드·수집은 바꾸지 않으며 원천 provider·Geo를 호출하지 않는다.

`GET /v1/service/exports/fuel-stations/{station_key}/price-history?product=&from=&to=&limit=&cursor=`

- `station_key`는 기존 주유소 export의 `natural_key`(OpiNet 안정 ID, 선행0 유지)다. 기존 service token 헤더와 실제 peer CIDR 인증을 상위 router에서 상속한다. 미인증/없는 주유소키는404다.
- product는 생략하면 모든 유종, 지정하면 해당 코드다. from/to는 timezone이 있는 ISO시각이며, 기본 종료는 요청 시각·시작은 종료30일 전이다. 종료 이후의 미래는 허용하지 않고 한 조회 창은 최대366일이다. 값은 유종별 `product_code, observed_at, price`이며 null 가격은 그대로 유지한다.
- limit은 모든 유종을 합친 한 페이지 전체 행수이며 기본1000·최대5000이다(유종마다의 상한이 아님). 전체 history 스캔 없이 주유소 FK·source·시각 범위를 제한하고 최신 observed_at/id 순 keyset으로 limit+1개만 읽는다. raw payload는 읽거나 내보내지 않는다. 기존 station/observed 복합 index를 활용하며, 실제 PostgreSQL 계획·실측 확인은 최종 gate다.
- cursor는 같은 station/product/시각 창·성공 수집 revision을 고정하고15분 동안 유효하다. 수집 성공/실패 상태·같은 원천시각의 교정(updated_at)이 바뀌거나 만료되면409로 첫 페이지부터 재시작한다. 다른 필터·변조 cursor는422다. mutable history correction을 ID 상한만으로 동결됐다고 간주하지 않는다.
- 응답 meta: generated_at(응답 생성), source_collected_at(이 페이지 이력의 실제 수집 시각 중 최솟값; 빈 범위는 마지막 성공), source_status(ok/stale/failed), item_count(페이지 건수). 성공 근거가 없으면503 problem + meta(source_status=failed, source_collected_at=null, item_count=0)이며, 실패/노후 후의 기존 이력은200 stale로 유지한다. 한 주유소·유종·기간의 합법적 빈 범위는200/0건이다. 원천 전체가 빈 성공이라는 의미가 아니다.
- weak ETag는 generated_at·cursor 재발급시각을 제외한 데이터·상태·페이지 의미로 계산한다. 변경 없으면304이며 status 변화는304로 숨기지 않는다. 후속 페이지가 있으면 수집 mutation revision과15분 cursor bucket도 ETag에 넣어 만료 전에 새cursor를200으로 재발급한다. 512byte 이상이면 gzip을 지원하며 CPU 사용을 위해 compresslevel1을 쓴다. DB snapshot을 반환한 뒤 JSON/gzip을 만든다. Cache-Control은 private,no-cache다. 새 브라우저 프록시/토큰을 추가하지 않는다.

```json
{"meta":{"generated_at":"2026-10-23T00:00:01Z","source_collected_at":"2026-10-23T00:00:00Z","source_status":"ok","item_count":1},"station_key":"A0000001","items":[{"product_code":"B027","observed_at":"2026-10-22T00:00:00Z","price":1700.0}],"next_cursor":null,"has_more":false}
```

## 휴게소 유가

`GET /v1/service/exports/rest-area-fuel-prices/{station_key}/price-history`는501 application/problem+json이다. 현재 transport는 휴게소 유가 이력 표를 저장하지 않는다. 이 PR에서 새 이력 표를 만들지 않으며, 생성 여부는 소유자 결정으로 남긴다. 현재 값은 기존 `/rest-area-fuel-prices`를 사용한다.

검증 대상은 정상/유종/시각·상한·cursor/인증/빈 범위/실패 stale·304상태변화/gzip·OpenAPI/TypeScript다. WSL·Docker·CI·2인 적대 리뷰·live API/UI는 최종 HEAD로 검증한 뒤 수용한다. Map 담당에게 PR 번호와 위 예시를 운영 배포 전에 전달한다. Map은 이 API를 요청 때 프록시하며 가격 이력을 Valkey에 저장하지 않는다(ADR-114).


첫 적대 리뷰에서 TTL·수집 mutation revision이 ETag에서 빠져 만료 cursor를304로 고정하는 문제와 같은 원천시각 교정을 감지하지 못하는 문제를 확인했다. has_more 응답의 ETag에15분 bucket+mutation revision을 포함하고 state.updated_at을 revision에 반영했다. 원천값이 같은 새 성공·첫 페이지 밖 같은 source-clock 교정·16분 경과 후 조건부 재조회 모두 사용 가능한 cursor를200으로 다시 받는 회귀를 추가했다. station은 id열만 읽으며 휴게소OpenAPI도 기본501·미인증404로 맞춘다. 최초SQLite18 PASS208.92초, TTL추가1 PASS12.46초. 최종회귀·PG·리뷰는 수정HEAD로 다시 확인한다.


최종 실제 PostgreSQL21 PASS291.75초와 격리 실제HTTP8개(304/8건전체keyset/gzip/인증·입력/실패stale·cursor409/휴게소501)를 확인했다. Docker는20 PASS·1실패였으며 `Vary: Accept-Encoding, Origin`의 합법적인 CORS 추가값을 exact equality로 거부한 테스트 전제 문제다. required token 포함 검사로 고쳤고 해당 Docker 회귀를 다시 실행한다. 제품 응답을 CORS에 맞춰 약화하지 않는다. 전체CI/통합full/실제PG계획·운영수용은 남아 있다.
