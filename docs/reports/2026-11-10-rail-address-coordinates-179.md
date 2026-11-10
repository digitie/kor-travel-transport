# 2026-11-10 — #179 역 좌표와 Dagster CPU

## 상태

주소 기반 좌표 보강 코드를 구현했고 WSL/Docker PG18 집중 검증은 각각101개가 통과했다. 겹치는 SQLite47개·Dagster53개·API1개는 합산하지 않는다. 현재 운영 API/수집기는 아직7a5d0c4이며 새 이미지·공식 철도 전용 job·Map export 실제 수용은 다음 단계다.

## 원인과 입력

[#179](https://github.com/digitie/kor-travel-transport/issues/179)의 최초1466개 중NULL173개(일반160/도시13)는 당시 관측이다. 이번 read-only 현재 DB는NULL171개(일반160/도시11)다. 기존 수집기는 지오코딩을 실행하지 않고 KRIC의 코레일 공식 stationSeq 링크와 정확한 역명 연결 좌표만 썼다. 현재 코레일 공개 좌표281개와 과거 KRIC 링크·공개 안내의 식별자/표기가 일치하지 않는 경우가 있다. 여수엑스포는 공식 안내의 `stationCode`도NULL이며 별도 역명·코드 매핑을 추정하지 않았다.

기존 VWorld SDK의 주소 조회로 원천 `전남광주 여수시 망양로 2`가 정확한 도로/건물번호로 정제되고127.74889094082855/34.753114229613544를 제공하는 것을 별도 진단 조회로 확인했다. 이는 운영 적재가 아니다. 장소 검색은 같은 이름의 승강장·버스정류장·주차장 등16개를 반환하므로 그중 하나를 이름만 보고 채택하지 않는다.

## 구현과 경계

- 기존 `place_location_collection_job`과 VWorld SDK `get_coord`·공개 parser를 사용한다. provider wrapper·새 키·SDK 변경·스키마 변경은 없다.
- 좌표가 없는 역만 조회한다. 입력의 시도·시군구·도로/법정동·건물/필지 본번과 부번, 응답 EPSG:4326·유한 국내 좌표를 모두 확인한다. 상세 주소가 없거나 응답이 불일치하면NULL을 유지한다.
- 기존 VWorld 호출 원장·10000회/일 예산·설정 간격·프로세스 lease를 함께 사용한다. receipt에는 원천 주소·역명·주소 종류·입력 지문을 남겨 주소가 바뀐 경우 이전 결과를 재사용하지 않는다. 키·query URL 원문은 저장하지 않는다.
- 네트워크 중 DB transaction을 보유하지 않는다. 응답 뒤 짧은 catalog 잠금과 행 잠금 아래 원천 이름/주소가 같은지 확인하고 좌표를 저장한다. 수집 중 자료가 바뀌거나 공식 좌표가 먼저 들어오면 덮어쓰지 않는다.
- 원천 `last_seen_at`은 보강 시각으로 변경하지 않는다. `_vworld_address`와 `coordinate_source=vworld_address`로 출처를 구분한다. 다음 KRIC 수집이NULL을 주어도 같은 역명·주소의 검증된 보강은 보존하며, 공식 새 좌표나 원천 변경은 우선한다.
- 기존 API의 실제 값 지문이 새 좌표를 감지하므로 다음 export 본문이 새로 구성된다. 이전 cursor의 불변 본문은 보존한다. Map에는 코드 변경이 필요 없다.
- VWorld만 역 stream을 opt-in한다. 카카오의 기존 버스·항구 대상을 확장하지 않았다. 기존 op에 선택 `rail_only=true`를 추가해 수동 후속은 철도만 처리한다. 정기 일정·동시성·48시간 KRIC 참조 보호를 바꾸지 않는다.

## 집중 검증

틀린 시도/시군구·도로/건물번호·좌표계·NaN/Infinity·불완전 응답 거부, 출처/주소 변경과 공식 좌표 우선, 버스·항구를 조회하지 않는 철도 전용 저장·호출 재사용, 새 export/ETag 무효화와 이전 cursorNULL 보존, 기존 Dagster op의 철도 전용 config를 검사했다. 일반철도 source·기존 장소/카카오·Dagster 회귀를 WSL/Docker PG18에서 검증했다. 전용 PG는 정확 CID/label을 확인해 종료·제거했다.

처음 QA env의 구 KRIC import 경로 오류와, 새 API 시험에서 필수 nationwide head를 빠뜨린503 실패는 보존했다. 기존 pinned provider source를 연결하고 fixture를 보완했으며 제품의 오류를 빈 성공으로 바꾸지 않았다. 새 Ruff 진단은0, 기존10개는 그대로다. 후속 import 정렬/주석 보완은 제품 로직과 구분한다.

## Dagster CPU 실제 관측

| 표본 | 초 | 컨테이너 CPU | 코드 서버 본체 | 가장 큰 자식 | 메모리 |
| --- | --- | --- | --- | --- | --- |
| 처음 | 8.5 | 71.04% | 5.41% | 58.96% | 762.7MiB / 2.5GiB |
| 후속 | 8.47 | 68.77% | 5.55% | 57.61% | 862.4MiB / 2.5GiB |

Docker CPU는 코어 하나를100%로 표현하며 호스트는4코어다. 최초71.04%는 전체4코어의 약17.8%에 해당한다. 두 표본의 부하·job 상태는 다르므로 개선율로 비교하지 않는다. 처음에는 고속도로/KRIC, 후속에는 공항/KRIC이 STARTED였다. 후속의57.61% 자식은 생성37.5초인 spawn worker이며 서버 본체는5.55%였다. 이 표본에서 수집 자식의 비중이 가장 컸지만, Python 함수별 hot stack이나 유휴 p95를 측정한 것은 아니다.

Transport runtime/CID·CPU quota·동시 실행 한도·공용 daemon은 변경하지 않았다. CPU 숫자만을 이유로 실행 수집을 취소하거나 동시성을 늘리지 않았다. 반복 비용 추가 검산은 step 프로세스 시작/모듈 import와 실제 수집 처리 시간을 분리하는 것이 다음 후보이며, 이번 관측을 CPU 최적화 완료로 쓰지 않는다.

정본 `transport-rail179-20261110/plan.json`, `pg-qa-results.json`, `cpu-summary.json`을 사용한다. Weather main3bcda7e1 배포/캐시 완료는 [별도 기록](https://github.com/digitie/kor-travel-weather/pull/221)이다. 역 보강의 운영 저장 수량·남은NULL과 공식 job은 실제 결과 후 정산한다.
