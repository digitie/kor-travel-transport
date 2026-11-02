# 다른 지역 시간표·Opinet 집계 기준·VWorld 후속

현재는 진행 중이다. 시간표 초도 채움과 새 집계 기준의 운영 반영을 끝내기 전 전체 완료로 기록하지 않는다.

## 2026-11-02 — 다른 지역 저장 관측·오피넷 이번 수집분 집계 수정

- 다른 지역의 평일 저장은1108역 중1077역,31역은 제공기관 자료 없음이었다. 토요일/휴일 초도 조회는 기존 정기 run39dccec5/앱5199가 이어받고 있어 전체 완료로 표시하지 않는다. 대구94역·광주20역은 세 운행일 저장됐다.
- 서울역·수원·반월당·녹동·판암·개화6역의 실제 PC1440/모바일375,24개 운행일 API-DOM 행/시각/첫차·막차가 통과했고 세션/자식 종료를 확인했다.
- Opinet09:16 KST의 실제 성공5169/공식9a9734ad에서 보유 최신가격30229건·지역1194행·일별 통계·공개 포인터·지도 API-DOM은 기존 정의로 일치했다. 추가 감사에서110건이 이전 관측값임을 확인했고 인간은 이번 성공 수집분만 집계를 선택했다.
- 새 기준은 collected_at=성공 세대만 포함한다. 같은 세대의 구 모집단은 원자 정정하고 정상 재시도는 쓰지 않는다. 원본·지난 세대는 유지하며 migration·외부 재수집·cleanup을 추가하지 않는다. WSL/Docker PostgreSQL18 관련9개씩과 현재 세대 정정 실패/보존/재시도2개씩을 통과했다. 운영은 아직984/f807이며 새 소스는 배포 전이다.
- 다음 한 작업은 새 백엔드 이미지를 빌드하고 기존 worker의 정상 종료 뒤 API·수집기에 반영해 현재 성공 세대를 정정·검산하는 것이다. 원 일정19·환경·다른 서비스는 보존하고 새 리뷰/백업·복원 게이트를 만들지 않는다.
- VWorld 입력은 비공개로 보관했으며 값은 Git·문서·로그에 쓰지 않았다. 시간표/Opinet 작업을 마친 뒤 Weather·Transport에 적용하고 실제 타일을 확인한다. 현재 지도 타일 오류와 통계 수치 대조 통과는 구분한다. 자동후속이15분 간격으로 이 채팅에서 이어받는다.

## 실제 증거

원장은 C:/Users/digit/.codex/tmp/transport-other-regions-opinet-20261102/에 있다. observation-latest.json은 기관/운행일별 저장·미시도·자료 없음, control-plane-latest.json은 실제 공식 run, rail-regional-ui/results.json은6역/2너비/24개 운행일의 실제 대조다. opinet-arithmetic.json과 fuel-after/results.json은 구 보유가격 모집단의0불일치 증거이며 새 정의의 완료 증거로 바꾸지 않는다. opinet-cohort.json은 새 기준에서 제외할110개 이전 가격을 구분한다. 수집 가능한 자료가 없음과 실제 운행 중단은 다르다.

## 제공기관 제약

KRIC의 두 기존 시간표 API가 토요일 등 일부 조회에서03 자료 없음을 반환한다. 평일/휴일 표를 복사하지 않는다. 새 공식 급행 표시 API 후보는 진단1회에서HTTP200/result30/KricAuthError였으며 기존 키로 승인되지 않았다. 그 API를 승인하면 빈 자료가 해결된다고 검증한 것은 아니다. 서울의 공개 CSV는 확인 시2025-09-30 파일이므로2026년 현재 운행표로 자동 대체하지 않는다.

[기존 요일/시간표 API 계약](https://openapi.kric.go.kr/rips/M_01_02/detail.do?id=182&lcd=C&operation=stationTimetable&service=convenientInfo), [서울 공식 CSV 정보](https://data.seoul.go.kr/dataList/OA-22522/L/1/datasetView.do).
