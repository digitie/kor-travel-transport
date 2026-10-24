# VadaHub 배편 기준자료 통합

## 범위와 데이터 계약

사용자의 최신 소스 배포·VadaHub 배편 표시 요청에 따라 기존 TAGO 저장 운항시간표와
VadaHub 기준자료를 같은 배편 화면에서 제공한다. provider는
`python-vadahub-api@4bc0164e48799bba5488f91ea1a06b5e2e86de78`를 직접 소비한다.
SDK의 카탈로그·공개 Chromium 다운로드·GDAL 파싱·출도착지 해석을 backend에 복제하지 않는다.

여객항로(meta63/layer500059), 도선항로(meta52/layer500048), 관광지 여객선
시설(meta3076/layer501304), SDK의 명시적 공식 터미널 CSV 보완 원천을 구분한다.
마지막 자료는 `data.go.kr:15148558`이며 VadaHub 미제공 터미널 SHP를 확보했다고 표시하지 않는다.
원천 이력일은 내용 조사일·현재 운항일과 다르다. 원천 ID의 선행0·원문 속성·URL·SHA·수집시점을 보존한다.
CRS 미확인 좌표와 도선 출도착지는 추정하지 않으며 이 자료로 현재 운항시간을 생성하지 않는다.

## 저장·재개

migration0035의 `ferry_reference_snapshots`는 4개 원천 각각의 정상 typed 응답과
최근 시도·실패 종류를 저장한다. 검증된 전체 응답만 원자 교체한다. 비어 있음·중복 ID·다른
dataset 응답은 실패로 남기며 이전 성공 자료를 유지한다. 한 원천 완료마다 commit하여 중단 뒤
정상 원천은 재호출하지 않는다. 브라우저 대기 중 DB transaction을 유지하지 않는다.

공유 volume `/app/collector-state/vadahub`의 프로세스 간 lock으로 중복 실행을 막는다.
SDK LocalArchiveStore가 SHA 검증·immutable 원문·manifest·고아 복구를 맡는다.
SHP 원문은 같은 layer의 최근 7일 보관본을 재사용하여 DB 저장 실패 뒤 재다운로드를 줄인다.
공식 CSV는 실패 시 작은 단일 파일을 다시 다운로드한다.
매일03:15 KST job이 누락/실패 원천을 보충하며 정상 원천은 7일 guard를 적용한다.
부분 실패는 성공 저장 후에도 Dagster Failure로 보고하고 자동 외부 호출 재시도는 하지 않는다.

## API·화면

`GET /v1/transport/ferry/reference`는 DB만 읽고 4개 원천의 data/null·실패 상태를 반환한다.
기존 항구 코드와 이 자료의 원천 ID를 자동 통합하거나 시간표 조회 키로 사용하지 않는다.
화면은 항로·기항·구간·시설 주소/연락처·조사년도 검색, 20개씩 페이지, 미수집/검색없음/실패 뒤
정상본 상태와 원문 링크를 제공한다. 기존 시간표 조회는 별도로 계속 이용한다.

## 검증·배포 원장

구현 및 검증 진행 중. 실제 공개 SDK 수집에서 여객항로424·도선34·시설109·공식터미널76행을
확인했다. 실패·불완전 응답·취소·재개·읽기 전용 API를 포함한 WSL 대상90개 검증이 통과했다.
최종 CI·독립 리뷰2·Docker·반응형 live UI·배포 SHA와 운영 수용 결과는 완료 후 아래에 기록한다.
