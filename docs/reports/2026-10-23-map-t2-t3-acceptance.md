# 2026-10-23 — Map T2/T3 제품 수용과 운영 잔여 gate

## 범위와 운영 경계

T1 행정주소·T4 가격이력·T5 빈 응답 보호(PR108~110)는 먼저 배포했다.
이 문서는 이후 T2 현재 상태와 T3 참조 API 및 필수 KAC quota 복구를 정산한다.
새 경로는 모두 기존 service token/peer 허용 규칙과 OpenAPI를 사용한다.

제품이 머지돼도 새 API의 운영 수용은 끝나지 않는다. T2/T3 collector flag는 defaultOFF이고
운영 schema0030~0033 적용·API/CS 배포·실제 source head bootstrap은 별도 승인된 drain 절차다.
운영 Fuel run과 공용 daemon/다른 서비스는 이 제품 검증에서 변경하지 않았다.

## 제품 PR과 최종 검토 SHA

| PR | 제품 | 최종 SHA | main 머지 |
| --- | --- | --- | --- |
| [114](https://github.com/digitie/kor-travel-transport/pull/114) | traffic/current·공통 고정 snapshot/schema31 | 75a2c90eb537bc203c2cf40af7618cf075e6aaff | 7c1ea0c3439b0bbd792f3575b487f06939cda804 |
| [115](https://github.com/digitie/kor-travel-transport/pull/115) | bus membership/schema32·참조 | e8ab14a771e0ac51c806d2f444751b4f8e140246 | 7b2f2a8598bbcd4d200762a2d868f9279452aa70 |
| [116](https://github.com/digitie/kor-travel-transport/pull/116) | ferry 참조·core/좌표 성공 분리 | 8ade282470d52cef041843156e1dceede9dbb3dc | 933cac6f59639eecc3f64ef1cd6e775557372641 |
| [117](https://github.com/digitie/kor-travel-transport/pull/117) | rail 참조·기존 persisted mapping 정본 | 4ab0ed2d5a8554de54a15f6efc024cc0bfb9da46 | 488d85b8d8332eaab68f682f92d0a26087d01e2d |
| [118](https://github.com/digitie/kor-travel-transport/pull/118) | parking/current/schema33·SDK 엄격 승인 | 7c62c7ff2189711218021a7e62b59fa3513a6ebd | 최종 CI 대기 |
| [119](https://github.com/digitie/kor-travel-transport/pull/119) | 원래 KAC quota deadline·복구 fence·비밀정보 제거 | bd1d945e2fe3d8c8f00af72e181307e5911a8d10 | 최종 CI 대기 |

각 최종 SHA는 James/Popper 두 독립 적대 리뷰 PASS/OPEN0이다. 최초 발견한
freeze 경쟁, 승인된 정상0 처리, 늦은 실패의 새 head 오염, 원천 clock 불일치,
주차 원문 오류의0/현재시각 치환, 정상 IIAC 초단위 거부, quota 역전/비밀정보 노출을
각각 재현·수정한 뒤 재검토했다. 리뷰 PASS와 전체 CI/운영 PASS는 서로 다른 gate다.

주차 provider 경계는 형제 SDK public API다.
[SDK10](https://github.com/digitie/python-krairport-api/pull/10)(35d265a2, merge7913cbf6)는
명시 성공 header·total/items/page 완결·크기 제한·안전한 ParseError를 보장한다.
[SDK11](https://github.com/digitie/python-krairport-api/pull/11)(6c9aa9ae, mergeb645dc53)은
엄격한 숫자·실제 KST 시각을 typed 값으로 제공한다. 두 PR은 각각 두 리뷰·정확 CI·로컬 전체
220/266 PASS와 정적 검사를 마쳤다. 기존 provider HTTP/느슨한 legacy parser는 변경하지 않는다.

## 검증 근거와 범위

- PR114 정확 CI PG1050 PASS/2 SKIP, 동일 제품 로컬 전체 PG1050/2 SKIP,
  최종 Compose1032/20 SKIP. PR115 최종 CI green, 수정 전 전체 제품 PG1058/2 SKIP에
  최종 경쟁/원천 clock delta PG5 PASS·집중23 PASS와 Compose23/2 SKIP를 더해 확인했다.
- PR116 정확 CI PG1066 PASS/2 SKIP, PR117 정확 CI PG1070 PASS/2 SKIP.
  집중 PG42/40 PASS, 공통 Compose55 PASS/1 PG조건 SKIP다.
- PR118 최종7c62 PR CI의 전체 PG1083 PASS/2 SKIP(2023.69초), 정상 초단위/비정상 수치·시각 delta PG6 PASS와 Compose6 PASS,
  기존 source/current/API 집중 PG39 PASS, schema33 check/down32/up33/check를 통과했다.
- PR119 최종bd1의 Map flagON/OFF·blocked 연속 관찰·원래 만료 후 재시도·역방향 quota
  실패·원장 초도 성공·비밀정보 제거를 PG8 PASS/Compose8 PASS로 검증했다.
- 실제 TCP HTTP fixture: traffic8300행9건, bus1000행12건,
  ferry/rail각1000행20건, 최종 parking12개13건, 최종 admin collect/quota8건 PASS다.
  이는 격리 PG와 live-mode fake provider를 사용한 API 수용이며 운영 source 건수/수집 성공이 아니다.
- 기존 운영 HTTPS UI16건은 모바일/데스크톱 지도·목록·통계·타일을 읽기 전용 확인했다.
  새 T2/T3 Map reader UI는 아직 수용하지 않았다. CI `live-e2e=SKIPPED`를 PASS로 세지 않는다.
- snapshot API의 provider 호출·이력/raw SELECT0, pool 반환 뒤 직렬화,
  TTL410/재시작·서명 cursor·ETag304/gzip·권한 거부·source stale 보존을 확인했다.

실제 TCP 보고서는 작업 환경 `F:/dev/audit-reports/2026-10-23-remaining`의
transport114/115/117/118/119-http-report.json에 보관했다. fixture JSON과 소비자 절차는
[Map 인계](../map-service-exports-handoff.md)를 따른다. fixture 속도는 WSL 결과이며
Odroid ARM CPU/RAM·PG WAL 개선 수치로 환산하지 않는다.

## 남은 운영 수용

1. root가 실제 수집 run 종료를 확인한 뒤 공식 Manager/NVMe 배포 절차로 API·CS·schema를
   적용한다. 공용 daemon ON, gRPC12306, 타 서비스/instigator 복원을 지킨다.
2. source별 정상 완결 수집으로 head를 준비하고 flag를 단계적으로 켠다. 초도503을
   Map 빈 성공으로 바꾸지 않으며 실패 시 이전 성공 집합/stale을 유지한다.
3. Map은 기존 T1 `collection` parser와 별도로 새 `meta/snapshot_id` reader를 적용한다.
   limit 고정·cursor 완독·TTL410 첫 페이지 재시작·stale/정상 traffic0건을 실제 UI로 검증한다.
4. KAC 실제 quota 원래 until 보존과 만료 뒤 재시도를 운영에서 확인한다.
   반복 ICN 성공/blocked 관찰이 deadline을 연장해서는 안 된다.
5. source 저장 추가 비용·최초 freeze·GC·PG WAL·API p50/p95와 ARM CPU/RAM을
   같은 입력 최소3쌍으로 계측한다. 전체 Track1/2 또는 CPU/메모리 저감을 완료 처리하지 않는다.
