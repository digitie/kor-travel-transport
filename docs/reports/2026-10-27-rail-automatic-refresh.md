# 저장된 자동 역 매핑의 미리보기·적용 API 후보

`codex/rail-automatic-refresh`의 backend 전용 변경이다. PR149의 matcher 개선을 재사용하되,
기존 비어 있지 않은 자동 배열을 실제로 재계산하는 별도 관리자 경로를 추가한다.
[설계·요청/응답 계약](../design/2026-10-27-rail-automatic-refresh.md)을 따른다.

## 기준 소스와 변경 범위

PR149의536 위에서 작성하던8파일을 별도 임시 경로에 백업하고 SHA256으로 고정했다.
149와 UI150이 머지된 main `ca59458b3276a9f80284c3e086f902fa66e5e64f`로 fast-forward한 뒤
8파일의 바이트가 동일하고150의 유가 통계 컴포넌트·회귀 파일이 main과 동일함을 확인했다.
149의 완료 증거 작업트리와 운영4d는 수정하지 않았다.

이 후보는 기존 도메인 서비스·명시 schemas·backend main route·생성 OpenAPI와 회귀·한글 문서를
변경한다. Next UI/proxy·SDK·dependency·DDL·수집 코드·48시간 보호는 변경하지 않는다.

## 구현한 동작

GET/POST `/v1/transport/admin/rail-station-mappings/automatic`은 기존 관리자 토큰을 요구한다.
GET은 RR READ ONLY snapshot으로 저장 catalog·active 공식 code·기준 역·raw registry를 읽어
기존 matcher로 후보를 계산한다. 추가/해제/재지정/방법변경·수동 충돌·무결성 차단 사유와
기존/후보 두 지문을 반환한다. raw manual/note는 응답에 노출하지 않는다.

POST는 두64자리 지문만 받고 READ COMMITTED에서 KRIC try-xact lease→420054→registry row
잠금 뒤 입력과 두 지문을 다시 검산한다. 다른 writer의 commit을 기다린 경우에는 새 revision을
읽는다. 변경 FK 쌍만 clear/flush/assign하고 automatic 배열·mapping 갱신시각을 한 번 commit한다.
manual/note·catalog·기준 역·수집/달력/시간표 상태는 보존한다. no-op은 쓰기·시각 변경0이다.
인증 실패404·미준비503·경합/이전 지문409와 문자열 detail을 기존 UI 오류 계약에 맞춘다.

`station_count`는 public_file 장소 수가 아니라 active 공식 catalog 코드 수다.
`manual_mapped_count`도 raw 배열 길이가 아닌 effective 수다. 코드2개/장소3개 회귀로 구분한다.

## 실제 검증과 남은 게이트

처음 순수 helper RED는 ImportError 수집 오류1건이었다. API 연결 전 RED는 인증과 저장 입력이
정상인 GET이404를 반환한1실패로 보존했다. 구현 뒤 WSL 집중 검증은 **56통과**다.

| 범위 | 통과 수 | 확인한 결과 |
| --- | --- | --- |
| 새 pure | 11 | 원문 note/추가 JSON 불변·순서 독립·해제/재지정·수동 우선/충돌·실제 FK 불일치·후보 지문 |
| 기존 matcher | 25 | KR/K4 범위·양쪽 중복 거절·manual/target 점유·기존 번호 전략 보존 |
| 실제 전용 PG | 11 | RC 대기 후 manual/reference commit 읽기·stale409, session/xact 양방향 배제·취소 후 해제, timeout409, flush 후 예외/취소/unique 실패 rollback, FK 교환·변경쌍만 UPDATE·method-only FK 쓰기0·no-op 쓰기0 |
| 새 API | 8 | preview/apply/no-op·기존 수동 응답/노트 보존·두 지문 각각409·미준비503·추가 manual 입력422·인증 선행404·OpenAPI·수동 저장 뒤 stale409 |
| 기존 수동 API | 1 | 수동 저장·해제·stale revision·대상 검증의 기존 계약 |

자기 전용 PG16·DB와 명시적 비중복 network를 사용했고 기존 정확 lock/pin runtime은 수정하지
않았다. 처음 선택한243 대역이 Weather 시험망과 겹침을 생성 전에 발견해244/28로 바꿨다.
운영·다른 프로젝트의 DB/컨테이너/네트워크에는 쓰지 않았다. focused 로그·JUnit·소스 manifest는
별도 임시 검증 경로에 보존한다. WSL/Docker 전체·CI·두 독립 리뷰·Next 연계는 아직 미완이다.

## 운영 수용과 분리

원본923자동/14수동/171미연결의 전체 일관 snapshot을 새로 읽지 않았으므로 실제 영향 수는
미확정이다. 제거·재지정·수동 충돌을 preview에서 구체적으로 확인한 뒤 실제 적용을 별도로
수용해야 한다. 이 PR의 synthetic fixture 성공을 서울역823의 실제 저장 FK 반영이나 시간표
복구 성공으로 세지 않는다. provider 요청·운영 DB/API 읽기·POST·직접 job·운영 빌드/배포는0이다.
