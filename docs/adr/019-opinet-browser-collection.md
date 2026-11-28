# ADR-019: 전국 유가(오피넷)는 공식 API가 아니라 공개 화면 브라우저 수집으로 모은다

- **상태**: accepted
- **날짜**: 2026-11-28 (사후 기록. 원 결정: 2026-09-19~20 T-040, PR [#30](https://github.com/digitie/kor-travel-transport/pull/30)·
  [python-opinet-api #18](https://github.com/digitie/python-opinet-api/pull/18))
- **결정자**: agent + human (사후 기록)
- **컨텍스트**: 통합 교통정보의 유가는 전국 주유소별 유종 가격·편의정보가 필요하다. 형제 라이브러리
  `python-opinet-api`는 오피넷 공개 지도/지역 화면을 Playwright로 조작해 읽는 수집기를 `opinet.experimental`
  네임스페이스로 제공한다. 오피넷에는 공식 API도 있으나, 이 저장소의 기록은 그 제공 범위와 "유료/제휴 조건과 상세 필드
  계약은 기능별로 확인한다"는 메모뿐이다([유가 분석 가능성 보고](../reports/2026-11-01-fuel-analysis-feasibility.md)).
- **결정**:
  1. 오피넷 유가는 `opinet.experimental`의 브라우저 수집기(`OpinetBrowserCollector`)로 전국 지역 화면을 순회해 모은다.
     공급자 화면 해석·지연·체크포인트는 형제 라이브러리가 맡고 Transport는 저장·통계·공개만 한다
     ([ADR-004](004-krairport-provider-library.md)와 같은 경계).
  2. 공식 API가 아니므로 사이트에 부담을 주지 않는 저빈도·throttle 수집으로 한다. 실행 간격은 provider의 throttle 정책을
     따르고 매 scheduler tick마다 재실행하지 않는다. 화면 구조 변경·자동화 차단은 실패로 기록하며 빈 성공 데이터로 덮지 않는다.
  3. 유가 수집은 고속도로 등 짧은 주기 수집과 별도 task·별도 job으로, 긴 시간 상한을 두고 실행한다
     ([ADR-009](009-durable-transport-collection-reservations.md)).
  → 세부: [수집기 기준](../architecture/collection.md)(간격·24시간 횟수·재시도·시간 상한·대기 상한),
  [유가 통계](../fuel-statistics.md)(통계·공개 세대),
  [오피넷 배포 인계](../reports/2026-10-24-opinet-deployment-handoff.md)·[재개 점검](../reports/2026-10-24-opinet-resume-review.md)(체크포인트·지연·실측)
- **근거**: 공식 API 대신 화면 수집을 고른 이유(비용·필드·호출 한도 비교)는 이 저장소에 **기록돼 있지 않다**. 당시
  기록(`docs/journal.md` 2026-09-19)은 이 수집기가 공식 Open API를 대체하는 것이 아니라 공개 화면 기반 실험 기능이므로
  pin된 provider의 throttle을 존중하고 원본/오류와 화면 변경 위험을 문서화했다는 내용뿐이다. 이 경로의 첫 성공 전국 run
  (승인된 수동 복구 재시도 run 13556)은 키 없이 주유소 기준정보 11,807곳과 가격 이력 59,035행(양수 29,426행)을 저장했다
  (`docs/journal.md` 2026-09-19, `docs/tasks-done.md` T-040).
- **결과 (긍정)**: API 키·제휴 없이 전국 주유소 가격과 편의정보(셀프·세차 등 화면 typed 컬럼)를 얻는다. 수집기 개선이 형제
  라이브러리에 쌓여 다른 프로젝트와 공유된다.
- **결과 (부정)**:
  - **취약성**: 공식 계약이 없어 화면 구조 변경·자동화 차단·응답 지연에 바로 깨진다. 실패를 빈 성공으로 숨기지 않으므로
    그동안 최신 유가가 늙는다. 공개 화면의 신선도는 마지막 시도가 실패이거나 마지막 성공이 24시간을 넘으면 오래됨으로
    표시하고(`fuel_read_model_freshness`), export 판정은 [ADR-013](013-internal-service-exports-for-map.md)이 정한다.
  - **긴 실행**: 화면 조작·무작위 지연 때문에 한 회가 길다. odroid(ARM)에서 성공 수집이 5,946~6,371초(약 1.7시간) 걸려
    시간 상한을 2시간에서 3.5시간으로 올렸고(2026-10-23), 이후 provider 최적화·체크포인트 재개를 더했다. 실행 시간·CPU
    부하가 공용 호스트에 영향을 준다.
  - **낮은 갱신 빈도**: 정기 실행이 하루 몇 회뿐이라 하루 안 가격 변화는 거의 보이지 않는다.
  - **운영 부담**: Playwright·브라우저 런타임을 backend 이미지에 실어야 하고, 체크포인트 볼륨·provider SHA 대조가 배포 절차에 들어간다.
- **후속**: 공식 API의 비용·필드·한도를 확인하면 이 결정을 재검토한다(대안 비교는 아직 없다). provider pin을 올릴 때 실제
  전국 run의 저장 결과로 수용한다(초기 화면 smoke는 수집 성공이 아니다).
