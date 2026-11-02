# 도시철도 코드 정본 역 상세

## 데이터소스 확인

형제 저장소 `F:/dev/python-kric-api`의 `StationCodeInfo`는 공식 운영기관·노선·역 코드와 각각의 이름을 함께 반환한다.
`KricClient.get_station_info`도 `StationInfo.station_name`과 세 코드·좌표·주소를 제공하며, 기관/노선 전체가 반환될 수 있으므로 세 코드를 대조한다.
`tests/test_live_envelope.py`의 실제 응답 형식 fixture 두 시험으로 역사 이름/좌표와 시간표의 원 코드를 확인했다. 이 검사는 mock HTTP이며 새 실키 호출·운영 수집 성공은 아니다.

따라서 **코드 정본의 역명과 시간표 조회에는 위치파일 이름 매핑이 필요 없다.** 기존 `kric_station_codes`의 이름을 직접 표시하고 ID로 저장 시간표를 조회한다.
기관/노선이 다른 동명 역과 선행0 코드를 보존한다. 기존 위치파일 연결은 좌표·주소·전화의 보조 자료로만 사용한다.
위치 연결이 없는 역도 목록·시간표에서 빠지지 않고 좌표가 없으면 지도 마커만 만들지 않는다. 기존 매핑/수집/외부 export 계약을 삭제하거나 바꾸지 않는다.

## API와 화면

- `GET /v1/transport/rail/stations`: active 공식 코드 정본 장소 목록. `source=kric_station_codes`, `provider_id=기관/노선/역 코드`, `id=코드 행 ID`.
- `GET /v1/transport/rail/stations/{code_id}/timetable`: 위치 FK 없이 코드 ID로 저장 시간표를 조회한다. `code_id`는 코드 정본 ID이며 `place_id=null`이다.
- 기존 `rail/timetables?place_ids=`·지도 예정 요약은 위치 ID 의미를 유지한다. 응답의 `code_id`는 additive 필드이며 기존 `place_id`를 코드 ID로 위장하지 않는다.
- 역 선택 상세 안에서 행선지별 예정 카드, 전체 시간표·첫차/막차 펼침, 노선도, 출구정보, 작은 출처/주소/전화 안내 순서로 보여준다.
- 예정 시간은 저장표 기준이며 실시간 도착으로 표시하지 않는다. 공휴일 미확인·새벽 운행일 미확정·수집48시간 초과·조회 중/실패 때 분 단위 예정 표시를 중단한다.
- 첫차/막차는 저장표 시각순의 첫·마지막 값이다. 자정 이후 운행일 연장은 미확정임을 밝힌다.
- **노선 순서/출구별 자료는 현재 저장 모델에 없어 미제공이다.** 코드 정렬을 노선 순서로 추정하거나 출구 번호/실시간 도착을 만들지 않는다. 제공 SDK의 별도 노선/시설 수집은 이 변경에서 실행하지 않았다.

## 검증과 한계

WSL·WSL Docker에서 관련 backend40개 통과/기존 PostgreSQL advisory lock 시험1개 제외,
관리자 UI4개 통과. TypeScript·변경 컴포넌트 ESLint·Next 빌드 통과. OpenAPI를 재생성했다.
SDK 응답 형식 fixture2개 통과. 최초 공용 QA 환경의 respx 부재와 Next 외부 node_modules 심볼릭 링크 빌드 실패를 보존하고,
SDK 격리 환경과 프로젝트 자체 npm 설치로 보완했다. 위 결과를 전체 PostgreSQL/실제 provider/운영 UI 수용으로 확대하지 않는다.

Firefox375/750에서 명시한 예시 자료로 컴포넌트를 촬영하고 페이지 가로 넘침0을 확인했다.
캡처: `C:/Users/digit/.codex/tmp/metro-station-comparison-20261031/after-375.png`, `after-750.png`.
운영 배포·DB 스키마/수집 설정·수동 수집·백업/복원 변경은 없다.

## 추가 반영 — 편의정보와 시간표 펼침 캡처

사용자 요청으로 노선도 영역을 생략하고 출구정보 자리에는 `역 편의정보`를 배치했다.
기존 KRIC SDK `parse_station_file_facilities`를 그대로 사용해 저장 원문에서 명시적으로 확인된
환승 가능·유실물 취급·안전발판·스크린도어·승강장 연결을 공식 코드 목록 응답에 포함한다.
UI는 시설별 설명과 역 주소·전화 안내를 보여준다. 자료가 없는 시설을 없음으로 확정하거나
화장실·엘리베이터·수유실의 위치/이용시간을 만들어 내지 않는다. 새 수집이나 provider 파서 복제는 없다.

Firefox에서 실제 React 컴포넌트를 로드하고 `전체 시간표`와 `첫차·막차` 버튼을 각각 클릭해
펼침/닫힘과 표시 시각을 대조했다. 375/750 두 폭에서 페이지 넘침과 pageerror는 모두0이었다.
고정 예시 데이터이며 실제 운영 역의 운행·시설 정보가 아니다.
캡처 경로는 `C:/Users/digit/.codex/tmp/metro-station-comparison-20261031/`의
`all-timetable-375.png`, `first-last-375.png`, `all-timetable-750.png`, `first-last-750.png`다.
캡처용 자체 Vite 서버는 확인 뒤 종료했다.

WSL 관련 API3개, UI5개·타입·변경 컴포넌트 ESLint를 통과했다.
WSL Docker UI5개·API3개와 Next 빌드를 통과했다. API 필드/DB 스키마 추가는 없다.
