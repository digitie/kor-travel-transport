# Map export 원천의 빈 응답·급감 보호

상태: 구현·검증 중. 운영 배포 전이다. T1~T4 export 확장과 Weather W1~W5의 실제 데이터 공개는 별도다.

## 문제와 계약

2026-10-23 KREX의 확인되지 않은 빈 응답이 성공 시각을 전진시켜 Map의 돌발106건을 닫은 사례를 보호한다. 같은 source·필터 scope의 이전 성공 개수보다25% 미만이거나 빈 응답이면, DB transaction/connection을 유지하지 않고 해당 source만 기존120초 상한에서 한 번 재확인한다. 정상 크기의 응답에는 추가 호출이 없다.25%는 파괴적인 급감을 확인하기 위한 보수적 정책이며 실측 CPU 절감 수치가 아니다.

재조회가 정상 크기로 복구되면 새 집합을 수용한다. 작은 집합·정상0건은 두 응답 모두 명시 total_count와 전체 페이지 수가 일치하고 크기가 같을 때만 수용한다. 단순 빈200 반복·총건수 누락·재조회 오류/시간 초과·불일치는 이전 원본/성공 시각을 유지하고 source 실패를 기록한다. 기본 수집 경로에 적용하므로 legacy export에도 보호가 작동한다. 실패한 돌발 legacy export의503 계약은 유지하며 소비자가 이전 집합을 보존한다. 새 snapshot opt-in의 stale200은 아직 구현하지 않았다.

`python-krex-api`의 incident()는 realTimeSMSList/count envelope를 검증한다. flow_all()은404를 total_count0/rawNone인 Page로 바꿀 수 있으므로 typed count0만으로 완결 증거를 인정하지 않는다. 명시 raw count/totalCount가 있는 경우만 사용한다. HTTP/provider 오류를 정상0건으로 바꾸지 않는다.

## 저장·비용 범위

성공 raw의 items는 유지하고 `_collection_guard`에 scope fingerprint와 item_count를 가산한다. 비교는 source index로 가장 최근 성공 raw 한 건의 개수만 SQL에서 읽으며 큰 본문을 Python으로 가져오지 않는다. 옛 incident raw는 전역 source라 배열 길이를 사용한다. 옛 traffic raw는 필터를 알 수 없어 비율 비교를 생략하되 빈 응답 보호는 적용한다. 새 traffic scope가 달라지면 옛 scope의 크기를 비교하지 않는다. 이력 fact 전체를 순회하거나 새 전역 잠금·DB schema를 추가하지 않는다. JSON 한 본문의 파싱 비용은 실제 PostgreSQL에서 별도로 확인한다.

원본 저장·성공 시각 commit 전에 guard를 마치고, 독립 traffic 성공을 incident 재조회 실패로 되돌리지 않는다. 유가12,600초/짧은 공개 잠금과 다음 예약 정합은 바꾸지 않는다.

## 검증·남은 수용

-106→빈/급감 후 재확인 실패, 마지막 성공·원본 보존, 초도 불확실 빈 집합 거부, 재조회 정상 복구, 정상0건 수용·급감 크기 불일치 거부, 필터 변경, source 독립 실패와404 변환 경계를 테스트한다.
- 실제 저장→legacy export에서106개200→불확실 빈 응답503→완결 확인된0개200을 확인한다.
- James 리뷰의P1을 재현·수정했다. 두 source가 동시에 의심 대상일 때 retry outer timeout이 provider 내부 source별 timeout과 같으면, 한 source 지연이 먼저 복구된 peer까지 실패시켰다. 최초 조회와 같은2배 outer 상한으로 개별 결과 반환 여유를 두고 실제 LiveProvider의30ms 축소 회귀를 추가했다. malformed empty가 SDK의KrexParseError로 변환된 경우도 한 번 재확인한다. 집중2개 PASS다.
- 전용 PostgreSQL·전체 회귀·Docker·CI·두 독립 적대 리뷰·live API/UI·운영 배포가 남아 있다. 원천 API를 부하 검증 목적으로 무제한 재조회하지 않는다.
