# VadaHub 배편 기준자료 통합

## 2026-10-25 운영 수용 완료

[PR129](https://github.com/digitie/kor-travel-transport/pull/129)/main
`a93dfba27283224e1cf091865f2c08d40cdd9dc3`를 배포했다. 운영 native run
`c8b70929-ba1a-4528-a662-b9b744f4bb9d`가 실제424+34+109+76=643건 저장 후 SUCCESS로 끝났다.
오늘 정기 실행도 정상 저장본을 재사용해 성공했다. 공개 [배편 화면](https://transport.digitie.mywire.org/ferry)은
로그인이 필요하며 실제375/1440px·검색·출처·기존 인천 운항시간표·로그아웃·release SHA 확인을 통과했다.
운영5개 역할 healthy·schema0035·공유 collector volume·18개 instigator의 정확한 ID/상태 복원을 확인했다.
공용 daemon/webserver의 이미지·시작 시각은 배포 전과 같다.

최종 후보0198e5d와 머지a93dfba는 같은 tree9deaf9c814d3b41c1a5de95a55e7e5e039a02a40이다.
CI40090454853/40090450929 모두 성공(backend1179/2skip·관리자248·웹130), WSL Docker1175/6skip이다.
James의 전화/조사연도 검색, Popper의 정상 ZIP 재사용·취소 기록 지적을 재현·수정했으며
CI green 후 독립 최종 리뷰2의 잔여 P0/P1/P2는0이다. ARM64 실제 SDK643건도 성공했다.
GDAL NumPy 모듈 메시지가 표준오류에 있었지만4개 원천 파싱·저장은 성공했다.

원격 Buildx 미지원 조회 옵션은 교체 전에 중단하고 plain inspect로 재개했다.
사전 archive CRLF와 공식 staging LF가 캐시를 무효화한 것도 재현했다. 소유 solver/client/controller/keeper
종료와 기존5개 역할·공용 plane 불변을 확인한 뒤749개 파일 bytes/실행 비트를 맞춰 공식 재개했다.
실행 중 metadata는 바꾸지 않았다. 운영 backend의 파일시스템 layers·실행 설정은 ARM 검증 이미지와 같다.
태그/attestation 식별자와 파일시스템 차이를 구분한다. 보호된 환경 백업·원래 instigator snapshot·이미지 ID·
복구 스크립트·native 결과는 NVMe `/mnt/media/kor-travel/build/transport/vadahub-deploy-a93dfba27283`에 둔다.

배포 후 유가 export HTTP200도 확인했다. 클릭150~850ms는 적용됐지만 오늘 전국 수집은08:03~09:05 KST,
약62분이어서30분 목표는 아직 미달이다. T-OPINET-30에서 추가 병목을 확인한다.
아래는 구현 당시의 상세 기록이다.

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

실제 SDK 자료를 저장한 native API/프로덕션 UI로375/1440px 검색·페이지·출처4개·결측 표시·
가로 overflow 없음2개를 확인했다. 관리자246개·타입/빌드, 기존 웹130개·빌드와
동일 tree(`a51b3f4f6a6e10bff8bc97eeb2eb74d94250ac8f`)의 Docker130개도 통과했다.
SDK 의존 조건으로 Playwright가1.64.1이 되어 별도 환경에서 OpiNet 실제 Chromium/
체크포인트45개를 실행해 모두 통과했다.
기존 운영 배편은2026-10-24 인천48·목포100편의 저장 조회를 확인했다.
10일 범위7530개 예상 스냅샷 중1545개 보관 상태이며 전국 보관 완결로 주장하지 않는다.

GDAL binding은 이미지의 `gdal-config --version`과 같은 버전을 native 설치한다.
이 비용이 매 소스 변경마다 반복되지 않도록 COPY 이전의 별도 이미지 cache 층에 둔다.
ARM 사전 빌드는 NVMe와 전용 BuildKit(메모리1536MiB·swap 포함2048MiB·CPU1.5개 상한)에서
진행하며 운영 컨테이너·공용 daemon은 교체하지 않는다.

기존 Dockerfile의 범위 의존성 설치가 lock과 다른 FastAPI0.162/SQLAlchemy2.1을
선택하는 것을 사전 빌드에서 발견했다. 고정 uv0.11.21로 committed lock을
검사·export하고 전체 의존성을 버전 고정 설치한 뒤 backend를 `--no-deps`로 설치한다.
`pip check`도 이미지 빌드 게이트에 포함한다. native GDAL만 시스템 ABI와 같은
별도 패키지이며 SDK의 VCS commit도 lock 그대로 유지한다.

WSL PostgreSQL 전체 회귀는1171개 통과·2개 건너뜀(57분22초)이었다.
이후 애플리케이션 Python·migration·의존성 lock 변경 없이 실제 Dagster in-process 실행을
추가해, 1개 원천 실패 때 정상3개가 commit되고 native run은 Failure이며 앱 실행의
orchestrator ID가 같은 것을 확인했다. VadaHub 대상7개가 통과했다.
최종 관리자246개·타입·빌드와375/1440px 실제 DB 조회·로그아웃2개도 통과했다.
최종 CI·Docker 및 운영 수용 증거는 [PR129](https://github.com/digitie/kor-travel-transport/pull/129)의
검증·배포 원장과 함께 읽는다. 소스 머지와 운영 교체를 같은 상태로 간주하지 않는다.

파싱에 실패한 원문을7일간 계속 읽는 재개 함정도 보완했다. 이전 오류가 있어도 최근 ZIP을
먼저 실제 파싱·검증하고 불량일 때만 새로 다운로드한다. 파싱 성공 뒤 DB 저장만 실패해도
정상 ZIP을 재사용한다. SDK archive를 지우거나 실패 원문을 덮어쓰지 않는다.
의존성·Chromium 준비도 정규화된 pyproject/lock 두 파일 뒤에 두어 앱·테스트 수정마다
재설치하지 않는다. 최종 editable 설치 뒤 stdlib 사전 컴파일 순서는 유지한다.
