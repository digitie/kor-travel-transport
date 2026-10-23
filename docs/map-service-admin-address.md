# Map service export의 행정주소 블록(T1)

상태: 구현·검증 중, 운영 배포 전. 기존 service token·실제 peer CIDR 인증과 legacy export의 현재 집합/실패 정책을 유지하는 가산 변경이다.

`GET /v1/service/exports/fuel-stations`, `/rest-areas`의 각 item에 `admin`을 추가한다. 기존 필드는 바꾸지 않는다. 주소는 Common의 `reverse_address_entries`를 동일 API DB snapshot에서 한 번에 읽으며, `fuel_station:{id}`·`rest_area:{id}`의 target_key와 Common `AddressTarget.coordinate_key`가 현재 좌표와 정확히 일치할 때만 사용한다. 반올림이나 새 geocoding 요청은 없다. provider는 현재 사용 중인 `vworld-kakao-reverse-v1` profile만 고른다.

```json
{"admin":{"legal_dong_code":"0123456789","admin_dong_code":"0012345678","sido_name":"시도","sigungu_name":"시군구","legal_dong_name":"법정동","road_address":"도로 주소","parcel_address":"지번 주소","postal_code":"01234","provider":"vworld","resolved_at":"2026-10-23T00:00:00Z"}}
```

위 코드는 실제 행정구역 코드가 아닌 선행0 보존 검증 예시다. 법정동코드는 ASCII10자리 문자열만 허용하고 잘못된 값은 null로 둔다. 미해결·좌표 불일치·지원하지 않는 provider/payload는 `admin:null`이다. 같은 좌표의 마지막 성공 주소가 갱신 오류로 보존된 경우에는 그 주소와 원래 resolved_at을 내며 API 조회 시각으로 확인일을 늘리지 않는다. 원천 주소·좌표를 덮거나 임의 코드 보정을 하지 않는다.

Map은 받은 법정동코드를 사용하며 주소 보충을 위해 Geo를 다시 호출하지 않는다. 이후 T3 역/터미널/항구 export도 같은 helper와 target kind를 재사용한다. T3 자체와 공통 메타·snapshot/ETag/gzip, T2현재 상태·T4이력은 이 PR의 완료 범위가 아니다.

SQLite 집중12개(주유소/휴게소·정상/1e-8도 좌표 변경/없음/잘못된코드/잘못된provider/오류후마지막주소) PASS. 전용PostgreSQL·전체 회귀·CI·두 독립 리뷰·live API/UI·운영 수용은 진행 중이다. 외부 주소 provider를 호출하지 않는다.
