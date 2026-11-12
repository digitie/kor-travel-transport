# 일반 주차장 소유권 이식과 읽기 비용 개선

Map 데이터 복제가 아니라 수집·저장·조회 기능을 Transport에 이식했다. 기존 공공데이터 SDK로
전국주차장 기준정보를 직접 수집하고 `0041_public_parking_lots`에 저장한다. 공항 실시간 주차는
기존 경로를 유지한다. [데이터 모델](../architecture/data-model.md)과 [설계](../design/2026-11-03-public-parking-owner.md)를 따른다.

2026-11-03 Weather와 Transport의 읽기 비용 개선·기능 이미지 반영을 완료했다. 일반 주차장의
기존 OpenAPI 수집은403이었으나, 사용자의 “파일이라 key 불필요” 지적 뒤 공식 공개 파일 다운로드가
키 없이 동작함을 확인했다. 이 다운로드 경로를 SDK18864a3/소비자f60b023에 반영했고 새 이미지
e7cdd88e를 배포했다. 공식 수집61213dad/앱5730 SUCCESS·18992시설 저장·DB/API/export·
실제 PC/모바일 수용을 완료했다. 키 활용신청·등록 확인은 필요 없다. 아래의 기존403·빈 화면 관측은 이력이다.

## 기능과 API

- `GET /v1/transport/parking-lots`: 검색 `q`, 상한 1,000개 `limit`, 세대·검색 조건에 결박한 `cursor`.
- `GET /v1/transport/parking-lots/{id}`: 요금·운영시간·주소·연락처·기관·자료 기준일. 이전 항목은 `is_current=false`로 구분한다.
- `GET /v1/service/exports/parking-lots`: 기존 서비스 토큰·실제 peer CIDR 보호 아래 원문을 포함한다. 완료본이 없거나 90일 경과면 503이다.
- `/parking-lots`와 교통 지도: 일반 주차장 목록·검색·선택 상세. 정적 총면수와 실시간 잔여면 미제공을 명시한다.
- `public_parking_reference_job`: 매월 4일 04:45 KST. 전체 페이지·수량 검산 후 원자 게시하며 실패한 부분 자료를 현재 집합으로 노출하지 않는다.

공식 식별자가 없을 때 기관 코드 하나로 여러 주차장을 합치던 경우를 수정했다. 무료 0·소수 시간은
보존하며 복합 요금 문자열을 임의 산술로 바꾸지 않는다. 잘못된 좌표는 지도에서 제외하고 목록에 남긴다.
일반 조회는 원문 JSON을 읽지 않고 지도 저배율 집계는 DB에서 수행한다. 요청 중 외부 수집은 없다.

## 반복 비용과 의미 보존

주차 이력은 선택한 공항·주차장의 불변 객체 참조 인덱스로 반복 전체 순회를 줄였다. 같은 cutoff 범위는
압축 결과를 공유하며 다른 공항의 시각 변화로 무효화하지 않는다. reference 발행은 같은 원자료를
digest와 DB 저장에 두 번 읽던 것을 한 번으로 줄였다. 기존 16MiB 상한과 digest 검산은 유지한다.
분석 cache는 32개 항목을 각각 SELECT하던 것을 한 번에 조회한다. 동일 JSON을 불필요하게 UPDATE하는
회귀는 재현 후 제거했다.

24만 행 합성 자료의 반복 render 중앙값은 주차장 1.061→0.067ms, 공항 2.125→0.246ms였다.
세 범위 출력 SHA가 같았고 인덱스 초기 생성은 710→826ms로 늘었다. 운영 API나 cold 성능 수치가 아니다.
분석 cache SELECT 32→1도 통제한 fixture 결과다.

## 검증과 적용 상태

- 기존 성능 집중 7파일: 격리 PG18 WSL 80개, Docker 80개 통과.
- 최신 통합 0041: 분석 22개·신규 주차장 8개·기존 지도 4개 묶음 WSL 34개, Docker 34개 통과. 위 80개와 겹치므로 합산하지 않는다.
- 실제 0040→0041에서 기존 fixture 보존·revision·새 표를 확인했다.
- 별도 Root WSL SQLite 주차장·gateway·일정 묶음 52개 통과. 전체 시험 통과로 바꾸지 않는다.
- 프런트 집중 Vitest WSL·Docker 각각 78개, type-check·수정 파일 ESLint 통과.
- 취소·부분 페이지 실패·중복·0건·세대 전환·공개 원문 비노출·일정한 SQL 수·인증·지도 좌표 격리를 확인했다.

최종 제품 `dc7a9ff0dd20aa200e8f4d76c58ee50dc9d9785f`의 CI 실행 `41569822363`에서
backend·frontend·transport-admin이 실제 SUCCESS였다. live-e2e는 SKIPPED였으며 아래
실제 Firefox 관측을 대신하지 않는다. 선행 제품 `7a406e5b9cfba447ab36ebceb5480af669924ce6`의
CI 통과 이력도 보존한다.
백업·복원과 새 독립 리뷰는 사용자 지시로 생략했다.
원본 삭제·과거 집합 정리·Map DB 접근·자동 복원은 수행하지 않는다.

## 파일 경로 보정 전 이미지·DB·일정 반영 이력

당시 Transport API·수집기는 제품 `dc7a9ff0dd20aa200e8f4d76c58ee50dc9d9785f`, SDK
`c936a5aa921318c606d1dbd157b657bc04d5cfd5`를 소비한다. 최종 ARM64 이미지는
`sha256:6c2f187b42ac26b91ebf6eb2322d158628c7cb7d21d11395ac2930b07a03cb4a`다.
API 컨테이너는 `1aafa91dd4a4c791bfb46480fef70f3e2a996bc4bc3520ab3f758bbb6d19f640`,
수집기는 `5ace6c1c7ca41bd030fc25f566ee8d3bd93717acde529410cd8aef6111af6f0f`이며
둘 다 healthy다. 실제 Cmd 포트는 API 12302·수집기 12306이고 PG18·
`0041_public_parking_lots`를 확인했다.

API·수집기 교체에서는 당시 관리 화면 이미지 `sha256:07e7b6e15218b5a8677fe0e52c095cefdbc050fa991873da1bb2663a8367f8ae`,
legacy frontend 이미지 `sha256:bbd4c9fa954228f75e9319e46435d9a2e53bcfc42412035b32cf9b17153b778c`,
gateway 이미지 `sha256:96868d9fa38f469a86d2f25787e43ee9ad330339d30be260aa9f5a338bb03751`는
이 최종 API·수집기 교체에서 그대로 보존했다. 다섯 역할이 healthy이며 기존 VWorld 키·
다른 환경·사용자 설정·다른 서비스도 보존했다. 일반 주차장 수집 활성화는 선행 배포에서
수행한 한 값의 변경이며 최종 metadata 정산에서 다시 변경하지 않았다.

사용자가 선택한 자연 drain을 기다렸다. KRIC 앱 실행 5573의 DB 상태는 success였고
314건이 stored 128건·no_data 186건으로 끝난 뒤 교체했다. 취소는 실행하지 않았다.
최종 배포 `213a490eb1`의 부모는 실제 1·`ContractError`로 종료했다. 실제 runtime 수용과
원 20개 일정 복원 뒤의 location reload 호출 경로에서 종료했으며 원 실패에는 세부 원인이
보존되지 않아 이를 추정하지 않는다. 이 부모 실패를 배포 전체 성공이나 실제 0으로 바꾸지 않는다.

별도 metadata 전용 `f3588f03ff`는 최초 Invocation `1ec6839642da459380b4613d36029677`에서
실제 0·MainPID 0·cgroup 부재·소유 자식 종료로 끝났다. Manager healthy와 원 20개 일정의
정확한 복원을 확인했고 runtime 교체·DB 쓰기·환경 쓰기는 각각 0이었다. 당시 정본 기록은
`/srv/ktdm-releases/transport-adopt-20261103T040453Z-d8eb0f06a259459ea2fa9d6903406a80`다.

그 뒤 빈 화면에서 발견한 두 문제만 수정한 UI 소스
`604b10d98d0394b28e9a9ea7c3f33933c102154a`를 관리 화면에 반영했다. 새 이미지
`sha256:9b8b7ad0f8f42945c0192d12982b194d8e75535dae5b87555930f7d58540eb64`,
컨테이너 `6d96fe4361c05f91dcebaed3244c0b01ab32ca1a506644de695503038c531440`이며
Cmd 포트12305를 유지한다. API·수집기·legacy frontend·gateway의 이미지/CID는 같다.
관리 화면 빌드7a15310d2c/첫Invocation0c7b65ed23ce4308879f125374e29ac6과
배포f0df6bcfea/첫Invocation1ad0fab7e94242d5a2f2de5de1e27f26은 각각 실제0·Main0·
cgroup부재·소유 자식 종료다. 다섯 역할 healthy와 Manager healthy를 확인했고 최종 정본은
`/srv/ktdm-releases/transport-adopt-20261103T045242Z-b2dc38b4a1a04fae9b4058571f75710d`다.
이 UI 배포의 일정 변경·DB 쓰기·환경파일 변경은0이다.

선행 이력도 보존한다. 최초 `7a406e5b` 이미지 `22b4139cd6ed43863a0bbbbfece95d8472f433e89ea2de309bbb386428c03a9a`의
배포 `69163455c6`은 원 19개 일정과 새 월간 일정의 카탈로그 차이로 복원 단계에서 실제 1이었다.
별도 `a916e88e94`에서 추가 항목이 `public_parking_reference_job_schedule` 하나임을 확인해
원 19개 상태를 복원하고 새 월간 일정 RUNNING을 보존했다. 이 선행 정산은 현재 20개 일정
정산과 구분한다. 최종 identity 빌드의 R1은 정제기 입력 누락으로 Docker가 시작되지 않았고,
R2는 build isolation 없이 설치할 때 setuptools가 없어 실패했다. 두 원 실패를 보존한 뒤
R3에서 Docker 자식 실제 0·부모 실제 0으로 위 `6c2f187b` 이미지를 얻었다.

## 시설 식별·충돌 투영과 오프라인 수용

첫 공식 작업 `2caad332-6041-4dc4-a7b7-b17ea1f2e68b`·앱 실행 5531은 번호 충돌로
`IncompletePublicParkingCollection`을 남기고 실패했다. 부분 자료를 게시하지 않았다.
원문 19페이지 18,994행을 보존해 번호가 전역 고유하지 않음을 확인했고, SDK의
`insttCode`·`insttNm` alias 누락도 재현했다. provider 라이브러리 PR21의 c936a5aa에서
alias 두 개를 수정했다. 기존 핀 69c8107의 다른 제품 코드와 의존성이 동일함을 파일 비교로
확인했으며 소비자는 typed 기관 필드를 사용한다.

번호·기관·NFKC 명칭·주소를 결박한 보존 원문의 고유 시설은 18,992개다. 원천 정보가 달라지는
두 그룹은 typed 공통값만 유지하고 충돌하는 면수·요금·시간 등은 미제공으로 둔다. 좌표 한쪽이
충돌하면 두 좌표 모두 미제공으로 두며 비고에는 고정 안내를 표시한다. 각 원문과 충돌 필드는
인증된 원문 경로에 보존한다. 전 페이지의 원문 건수 18,994개를 먼저 검산하고 고유 시설별로
한 번만 저장한다. 동일 원문 반복·페이지/전체 건수 불일치는 여전히 전체 게시를 거절하며
고정 실패 코드로 검산 사유를 남긴다.

최종 SDK 소비자의 PG18 WSL·Docker 집중 회귀는 각각 13개 통과했다. 페이지 안·사이의 충돌,
세 번째 변형과 여섯 순서의 같은 결과, 공통값·미제공 값, 원문 전체 보존, 완전히 같은 원문
반복 후 전체 rollback을 확인했다. SQLite 13개 회귀와 `uv lock --check --offline`도 통과했다.
보존한 실제 19페이지는 같은 순수 집계 코드로 18,994→18,992·충돌 2개, 원문 digest multiset
보존·반쪽 좌표 없음·충돌 필드 미제공을 확인했다. 이 검산은 DB·외부 API 호출 0, 원문 내용
출력 0, 원파일 SHA 불변으로 수행한 **오프라인 PASS**다. 보존 archive SHA256은
`a69b4df392babe6ee92a5952f2faf7f09f12a484ef62356af8e7c91010b06582`다.

## 공식 수집과 실제 화면의 미완 상태

수정 배포 뒤 두 번째 공식 작업 `c25937b9-728f-4d30-a2d6-70ea2a3d6e86`·앱 실행 5580도
실제 FAILURE였다. 앱 실패는 `TransportError`이며 수집기에서 같은 SDK로 진단한 공급자 응답은
403·`SERVICE_KEY_IS_NOT_REGISTERED_ERROR`였다. 분류 원장은 INVALID_KEY로 기록한다.
API·수집기의 유효 키는 같고 과거 배포와도 같았다. URL 인코딩·공백·설정 전달 형태 문제는
관측되지 않았으며 로컬 Map 환경에 대신 사용할 등록 키도 없었다. 키 값·URL·응답 원문은
이 문서나 진단 출력에 기록하지 않는다.

후속 사용자 지시에 따라 Map과 원 라이브러리 로컬 설정을 추가 확인했다. Map debug UI와
Claude checkout의 legacy 변수 `KRTOUR_MAP_DEBUG_UI_DATAGOKR_SERVICE_KEY`,
`KRTOUR_MAP_DATA_GO_KR_SERVICE_KEY`, `KRTOUR_MAP_ADMIN_DATAGOKR_SERVICE_KEY`에 있는
값과 `F:/dev/python-datagokr-api/.env`의 `DATA_GO_KR_SERVICE_KEY`는 모두 현재 Transport
유효 키와 같았다. 기존 현재 변수명만의 검사에서 빠진 Map legacy 이름도 포함했으며 고유 후보는
하나였다. 그 키로 실제 수집기의 SDK와 로컬 원 라이브러리에서 각각 단1회 조회했으나 둘 다403이었다.
대체 키 반영·환경 변경·재배포·공식 수집 재제출은 수행하지 않았다. 후보 값은 Git 밖600 파일로만
다뤘으며 출력하지 않았다. 새 원문은 `local-parking-key-discovery.json`,
`local-map-parking-key-expanded.json`, `local-parking-key-validation.json`,
`local-parking-key-local-sdk-validation.json`이다.

당시 일반 주차장 source의 `last_success_at=null`, `last_error=TransportError`였다.
목록은 HTTP 200이지만 빈 항목과 실패 표시를 반환하고, 인증 export는 완료본이 없어 503이다.
따라서 운영 18,992개 게시·실데이터 목록/상세/지도 수용을 완료로 표시하지 않는다.

Firefox 157의 PC 1440·모바일 375 관측은 모두 `NOT_READY/no_stored_rows`였다. 빈 화면의
가로 넘침 0·페이지 오류 0, logout 303·인증 저장소 정리·자식 종료는 확인했다. 이는 데이터가
있는 화면의 기능 PASS가 아니다. 이어 최초 수집 실패에는 완료된 저장 정보가 없다고 정확히
표시하고 PC 폼의 큰 빈 공간을 줄였다. WSL·Docker 관련8개씩 통과 후 최종 새 이미지에서
Firefox157 PC1440·모바일375의 안내·넘침0·페이지 오류0·로그아웃303·인증 저장소 정리·자식
종료를 확인했다. PC 검색 영역 높이는63.25px였다. 첫 관측은 안내문을 목록 내부에서 찾은
관측 스크립트 오류로 실패했으며 원 실패를 보존했다. `.public-parking-feedback`으로 조회
범위만 보정한 별도 관측에서 확인했고 제품은 재배포하지 않았다. 결과는 여전히
`NOT_READY/no_stored_rows`다.

당시에는 활용신청·키 등록 확인을 요청했으나 파일 다운로드를 놓친 판단이었다. 사용자 지적 뒤
그 입력 요구를 철회하고 아래 공개 파일 경로로 수정했다. 원403·실패·NOT_READY 증거는 삭제하지 않는다.
백업·복원 재도입, 새 리뷰, 원본 정리나 자동 복원을 추가 게이트로 삼지 않는다.

## 키 없는 공식 파일 경로 보정

공식 상세 페이지의 `std-download-manager.js`가 사용하는 공개 다운로드 경로는
`/download/columList.json?pk=15012896&ext=JSON`과 `/download/standard.json`이다.
포털 CSV/JSON 다운로드와 같은 원천이며 키·활용신청이 필요 없다. SDK에 전용 무인증 전송을
추가해 키가 설정돼 있어도 다운로드에 보내지 않는다. API 전송과 TPS 예산을 공유하고 종료한다.
전체 건수·컬럼·각 페이지 길이·다운로드 전후 메타데이터를 검산하며5만 건 상한 자료는 거부한다.
대문자 원문은 그대로 보존하고 typed 필드에 대응하는 책임은 SDK에 둔다. Transport는 기존
0041·복합 식별·충돌 공통값 투영·원자 성공 포인터 계약을 그대로 소비한다. 스키마 변경은 없다.

SDK18864a3의 WSL/Docker 관련32개씩·ruff·mypy, 소비자f60b023의 PG18 WSL/Docker14개씩과
lock 검사를 통과했다. 새 실제 공개 파일은 두 페이지10000+8994행·고유18992시설/충돌2개였다.
이 사전 검산은 운영 DB 쓰기0이며 공식 job 성공으로 바꾸지 않는다. 첫 새 빌드4358e08029는
BASE digest를 저장소 이름으로 해석해 실제1/Docker1/Main0/cgroup부재로 종료했다. 같은 소스·
wheel·Dockerfile의 BASE만 검증된 로컬 태그로 고친 별도R2 997556e2ab/첫Invocation
e33427a3eef24108a388cf26e38c525c는 실제0/Docker0/Main0/cgroup부재·native무인증 계약을 통과했다.

최신 API·수집기의 제품은 `f60b02327bb2c720c091b910d45ab330fea97fd0`, SDK는
`18864a3aa3314bcd4cbefb6fabcd589c5847f750`, ARM64 이미지는
`sha256:e7cdd88ed0fddd4880826e542d24222c7d79804ca1764f857ed7b4937a6dc9a5`다.
API CID는 `881082deacb887011b268f0c23f33655f353c4f00fb13e5595b43a24f246dde1`,
수집기 CID는 `fca04b02a1f0c21a1b9f01edf216b855a698c5b1cb6f6db3ea5f6a6b7ecb19cc`다.
배포7805f2ba09/첫Invocation2f2d4c04aa894e22911b1e83622dd268은 실제0/Main0/cgroup부재·
소유 자식 종료이며 다섯 역할 healthy·원20개 일정 복원·환경파일 동일성을 확인했다. API12302·
CS12306·관리 화면9b8b7ad0/12305·PG18/0041은 유지했다. 최신 Manager 정본은
`/srv/ktdm-releases/transport-adopt-20261103T114711Z-0c42bf2e590f4219998cdcb1a06340d9`다.
runtime 교체는 API·수집기2개뿐이고 다른 역할·다른 서비스·키·환경·스키마 변경은 없다.

공식 작업 `61213dad-ca2b-4fc2-8bfa-870b16c18f80`·앱5730은 실제 SUCCESS/success다.
제출 부모bc30e8c0b1/첫Invocation754a71612dc4441e8c98c8c220731c6a도 실제0/Main0/cgroup부재·
자식 종료다. 제출0과 작업SUCCESS를 구분했고 관측했던 run 부모·로그 자식 PID도 현재 부재다.
원문2페이지18994행·고유18992시설·충돌2개,0면18곳을 보존했다. 좌표 미제공751곳은 DB에 남기고
지도에서는 제외한다. 새 성공 포인터·실패 표시 해제·독립 고유건수·검색·커서·충돌 상세·지도 집계·
인증export200을 확인했다. 과거 실패와 원문은 삭제하지 않았다. 단일 native 관측의 목록100행은
321.02ms, 상세146.95ms, 검색1622.74ms, 인증export401.41ms였다. 운영 평균이나 개선 배율이 아니다.

Firefox157 PC1440·모바일375의 목록/상세에서 각 요금·면수·운영시간·주소·기관 DTO-DOM과
정적 기준정보 안내·넘침0·페이지 오류0·로그아웃303·인증 저장소 정리·자식 종료를 확인했다.
첫100행에서는 좌표 미등록 항목이 관측되지 않았으며 이 UI 항목은 별도 NOT_OBSERVED로 남겼다.
그 자료의 DB 보존·일반 목록/API 계약은 기존 집중 시험으로 확인했다. 첫 PC 지도 관측은 숨겨진
모바일 토글을 기다려 TimeoutError였고 로컬 continuation36221은 실제1로 종료했다. 원 실패를
보존하고 PC에서 항상 열린 필터를 그대로 사용하는 PC 전용 재관측으로 PASS를 확인했다.
모바일 원 관측은 PASS다. 추가 앱 배포·공식 수집 재실행은 없다.

첫 지도 PNG는 타일/상세의 로딩 중이었다. 별도 지도 관측에서 상세 렌더링과 network idle을
기다려 PC·모바일 선택 마커·실제 지도 픽셀·상세 화면을 다시 캡처하고 Root가 확인했다.
최종 지도 관측도 두 폭 PASS·넘침0·오류0·인증 정리·모든 소유 브라우저 자식 종료다.
원문은 `parking-keyless-build-r2/build-last-status.json`, `parking-keyless-deployment/deploy-last-status.json`,
`parking-keyless-job/last-job-status.json`, `parking-keyless-live-read.json`,
`live-parking-keyless/results.json`, `live-parking-keyless-pc/results.json`,
`live-parking-keyless-settled-map/results.json` 및 해당 PNG다.
최종 결박 `parking-keyless-final-evidence.json`의 SHA256은
`e12db4ade9cd7352753604bd8819c9ce3a6eab95a28d1f3f8e25685c1fcf1676`이다.
기존 미완 원장7243a85a와 새 완료 원장을 구분하며 원 파일을 편집하지 않았다.
f60b023의 CI41628896935/41628890856은 최종 관측에서 frontend·transport-admin SUCCESS,
backend 진행 중·live-e2e SKIPPED였다. 이 CI를 집중 검증·실제 Firefox 수용으로 대신 기록하지 않으며
PR173·SDK22는 Draft로 유지한다. 키 등록 입력이나 추가 배포/수집/백업·복원/리뷰는 남지 않았다.

Git 밖 증거 원장은 `C:/Users/digit/.codex/tmp/transport-map-parking-perf-20261103` 아래의
`parking-identity-build-r3/build-last-status.json`, `parking-identity-deployment/deploy-last-status.json`,
`parking-identity-metadata/deploy-last-status.json`, `parking-initial-job-r3/last-job-status.json`,
`parking-http-classification.json`, 키 값 없는 alignment/shape 원장, `parking-live-read.json`,
`live-parking/results.json` 및 두 PNG다. 최종 UI 원문은
`parking-ui-build/build-last-status.json`, `parking-ui-deployment/deploy-last-status.json`,
`live-parking-ui-fix/results.json`의 원 실패와 `live-parking-ui-fix-r2/results.json` 및 두 PNG다.
최종 CI 원장은 `transport-identity-ci-final.json`이다.
최종 결박 원장 `parking-final-evidence.json`의 SHA256은
`7243a85a16ba0a3d326c655cd2387f2f9d3ac2d7a1c104b3b0bcafaf45e2a4e6`이다.
이미지 반영 완료와 공급자 등록 확인이 필요한 데이터 미완을 함께 기록했다.

## 병행 Weather 완료 범위

병행 Weather는 별도 저장소 PR199의 제품 539d6c87·API 이미지 4c349d4c·schema0036을
반영했다. 기존 web·수집기는 보존했고 실제 locations 500행 200·조건부 304 본문 0을 확인했다.
최초 guard 503은 보존했으며 당시 보유자와 경합 단계는 확정하지 않았다. 합성 측정과
운영 응답을 섞지 않는다. Weather 최종 문서 소스 d5705ce1의 CI도 통과했다.
