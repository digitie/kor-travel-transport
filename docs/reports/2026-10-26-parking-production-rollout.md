# 2026-10-26 공항 주차장 통합 릴리스 빌드·배포

상태: 10월27일06:59 KST에 `7f01b013`의 공식 배포가 검증 완료됐다. 다섯 역할이 healthy이고 Transport 일정18개는 원상복원했다. 이후 실제 화면과 자연 수집·주차 통계 갱신 수용을 진행 중이다. 최초 모바일 분석504를 별도 실패로 보존하며 이후 성공으로 지우지 않는다. 사용자가 빌드·배포와 실제 화면·통계 갱신 검증을 승인했다.

## 현재 배포 결과

최종 unit은 `kt-transport-parking-7f01b013-20261027-r2.service`이며
2026-10-26 21:59:52 UTC(10월27일06:59:52 KST)에 `DEPLOYED_VERIFIED`·MainPID0·exit0으로 끝났다.
`instigators_paused:false`, `builder_started_by_this_run:false`, `child_known_ended:true`다.
API·관리자 영수증은 모두 full `7f01b0133dad73843ce61444830b1020cfd32f0a`이고 schema는
`0035_ferry_reference`다. 운영 schema 변경이나 환경 변경은 없다. 공용 daemon은 계속 RUNNING이다.

| 역할 | 확인한 image ID |
| --- | --- |
| backend·code-server | `sha256:6cc78ddafa825b2a1a081bced1778db6c5d12ddc4ec9b6e27f0aea16b2ea2e2d` |
| 공개 웹 | `sha256:ce8a837c9ddb5979199e0f17a257e87fbd09e599f4651121436548266fa5234f` |
| 관리자 웹 | `sha256:932bd51a49201bbce5d978ab24e2e6867d48d6343db02f6f5a63476dceea0966` |
| gateway | `sha256:96868d9fa38f469a86d2f25787e43ee9ad330339d30be260aa9f5a338bb03751` |

부모가 성공 원본 result/postflight/source-proof를 읽기 전용으로 회수해 WSL
`/var/tmp/codex-parking-deployed-proof-20261026.wf18co_h/`의 새0600파일에 보존했다.
다섯 역할의 고유ID·정확 image·healthy·실제 release를 대조한 후에만 실제 QA를 시작했다.
상태 복사에는 새 snapshot의10,509개를 사용했고 전 항목의 내용·소유권·권한을 확인했다.
이전 복구의10,476개를 재사용해 그 사이 새 artifact33개를 덮지 않았다.

앞선 수집 중지 기간의 과거 관측 공백은 새 수집·캐시 갱신으로 소급 복구됐다고 주장하지 않는다.

## 최초 후보와 기존 운영 이력

- 후보: `71a551ef7fa29957be018294363063e1870be011`. 제품 기준 `1e50dbc`와 backend/frontend/packages가 같고 PR137은 문서만 변경했다.
- 기존 운영: API와 code-server의 `a93dfba27283224e1cf091865f2c08d40cdd9dc3`, 관리자·공개 웹·gateway를 포함한 다섯 역할이 healthy였다.
- Manager `targets validate --json`의 대상은 `odroid`, 주소는 `192.168.1.13`이다.
- 앱·중앙 환경·Docker·staging의 실제 저장 장치는 NVMe이며 사전 점검의 가용 디스크는 252GiB다.
- 공용 Dagster 1.13.24와 세 location이 정상이고 공용 daemon·PostgreSQL이 running/not-paused였다.
- 운영 후보 사이에 Compose·배포 스크립트·Alembic의 의미 변경은 없다. 운영 파일 63개는 CRLF, 후보 Git archive는 LF여서 바이트가 달랐으며 CRLF를 LF로만 바꿔 대조한 결과 나머지 차이는 0이었다. 공식 배포 `.sh` 원문은 바이트도 같았다. 의존성 변경은 검증한 공항 SDK pin을 포함한다.

사전 점검 원장은 WSL `/var/tmp/codex-transport-release-20261026.GDf0xA/preflight.json`에 보존했다.
비밀 환경 내용은 보고서에 복사하지 않는다. 아래 항목은 실행 당시 이력이다.

후보 Git archive의 SHA256은 `e39953bd9f8ab5f25d5dc1d75e274d5d621a35f9eaae0fd1e8221a7fb3ad9459`다.
917개 member와 pax `comment`의 full 후보 SHA를 확인했다. 새 소유 NVMe 전송 디렉터리의
`parking-upload-71a551ef.yqykOe/candidate.tgz`로 업로드한 뒤 같은 해시를 재확인했다.
이 준비 단계에서는 운영 앱 소스·이미지·컨테이너·일정 상태를 변경하지 않았다.

첫 unit `kt-transport-parking-71a551ef-20261026`은 `ABORTED_BEFORE_STAGING`으로 종료했다.
자식 종료·일정 미중지·builder 미기동을 확인했으며 해당 audit/input/unit은 그대로 보존한다.
정확한 바이트만 허용하던 사전 guard가 위 줄바꿈 차이를 거부한 결과다. 새 실행은 CRLF↔LF만 다른
경우를 따로 입증하고, 내용이 다른 경우에는 계속 거부한다. 두 운영 env는 바이트·소유권·권한을
그대로 보존한다. 설치 overlay는 같은 내용과 경로·소유권·권한을 유지하면서 공식 install이
후보의 LF 원문을 설치할 수 있으므로 아래 두 정확한 해시만 허용한다.

- 기존 CRLF: `9322a6d9171c5b227fb3d7daa4cda49473e1556289cdd782ee831bc6f1ecab67`
- 후보 LF: `54eb658a1c7dcfe8b0ae4fac20ef88fff1f7b77335d05eec2fb3339564ce889b`

배포 제어 파일은 저장소 밖의 이번 전환 전용 산출물이다. 비운영 WSL 시험 39개를 작성자·부모·James가
독립 통과했고 James/Popper가 아래 정확한 파일에 최종 PASS를 남겼다. 일정 일부 복원 뒤 실패하면
최신 CS artifact를 보존하며, 중지 여부를 확인하지 못한 결과를 `paused:null`로 구분하는 회귀를 포함한다.

- controller SHA256: `dcf529aea8231d7bed0f22565e6b60f84bf86f5fa2a2124386baec91d64d500c`
- instigator helper SHA256: `c4f68d56cf16d5de8b2ffc61679bb8c891e295cd2d7b629554a3b68b8e5cd544`
- 새 unit: `kt-transport-parking-71a551ef-20261026-r2`
- 새 audit: `/mnt/media/kor-travel/build/transport/parking-release-71a551ef-20261026-r2`

## 최초 후보의 빌드 이력

운영 다섯 역할을 유지하면서 다음 순서로 이미지를 빌드했다. 시각은10월26일 UTC다.

| 대상 | 시작 | 종료 | 결과 |
| --- | --- | --- | --- |
| backend | 02:15:41 | 03:28:53 | exit 0, 4,392.796초 |
| 공개 웹 | 03:28:54 | 03:55:40 | exit 0, 1,606.118초 |
| 관리자 웹 | 03:55:40 | 04:36:03 | exit 0, 2,422.799초 |

중간에 로컬 WSL 연결이 일시 응답하지 않았으나 재시작 없이 복구됐고, 운영 호스트의 독립 unit은
계속 실행 중이었다. 중복 배포나 다른 프로젝트 프로세스 중지는 하지 않았다.

세 이미지 빌드 뒤 04:36:05 UTC에 계약 확인이 `ContractError`로 중단됐고, 복구 경로의 계약 확인도
실패했다. `-r2` unit은 04:36:22 UTC에 `UNKNOWN_NO_PAUSE_PERFORMED`로 종료했다. 결과는
`instigators_paused:false`, `child_known_ended:true`, `builder_started_by_this_run:true`다. 빌드 성공과
운영 배포 성공을 구분하며, 기존 원장은 보존하고 읽기 전용 진단 후 후속 절차를 결정한다.

읽기 전용 대조에서 원인은 Docker `Mounts` 배열 순서였다. backend/CS의 각 mount의
`Type/Source/Destination/RW`와 다섯 역할의 ID·image ID·StartedAt·healthy·paused 상태는 동일하지만
배열 순서가 달라 전체 dict 비교가 실패했다. 두 env·overlay fingerprint와 타 컨테이너 기준 상태의
차이는 0이었고 관리자 runtime SHA도 기존 `a93dfba`였다. 마운트 내용 변경을 허용하는 대신
나열 순서만 정규화하는 후속 절차를 검토한다. 세 완성 이미지는 모두 arm64로 확인했다.

후속 읽기 전용 관측에서 r2 복구의 `restore-operating-source`는 exit0으로 원본 소스를 되돌렸고,
`.release-sha`·`.transport-admin-release-sha`도 기존 `a93dfba`와 일치했다. staged marker는 없었다.
BuildKit의 이번 세 기록은 모두 Completed, Running은 0이었다. Transport instigator 18개는 모두
RUNNING, 대기/진행 run과 실제 CS worker는 각각 0이었다. builder는 원래 제한을 유지한 RUNNING이었다.
이 관측은 후속 전환 직전의 fresh pause/drain 증명을 대신하지 않는다. r2의 최종 결과명도 그대로 보존한다.

완성 이미지의 정확한 ID는 다음과 같다.

| 대상 | image ID |
| --- | --- |
| backend·code-server | `sha256:ce5b9ab7c96386a26ca741fe964754cf275e7618618a822123d8e5700ff5823a` |
| 공개 웹 | `sha256:ce8a837c9ddb5979199e0f17a257e87fbd09e599f4651121436548266fa5234f` |
| 관리자 웹 | `sha256:4f7257acca7194fe43fb53b9d6a2e13460ef8646fa5cbdece27cb296ec916329` |

## 후속 r3 실행

새 `parking_release_r3.py`는 기존 controller/helper를 변경하지 않고 상속한다. 마운트 순서만 정규화하고,
r2의 원본 소스·이전 이미지·schema·보호 파일·타 컨테이너·builder 원래 STOPPED 계보를 그대로 검증한다.
BuildKit manifest의 config digest와 각 build의 실제 시작/종료 구간으로 세 이미지의 연결을 입증하고
별도 prebuild는 다시 하지 않는다. 공식 backend/admin 원문과 정상 캐시 확인 build 호출은 그대로 유지한다.

첫 r3 리뷰의 P2는 실제 복구가 사용하는 이전 `rel-a93dfba27283` 태그의 ID 재검증 누락이었다.
현재 운영 tag 변경을 관측한 것은 아니다. 같은 rollback alias가 남아 있어도 실제 tag 변경·누락을
거부하는 두 회귀를 추가했고, 새 정확 파일에 대해 James/Popper가 모두 잔여 P0/P1/P2 없음으로 확인했다.

- 최종 r3 SHA256: `be7246c88f9dde1df1d3c0668c0216d86bd4ce307ce635550bec9eee2f326869`.
- 비운영 WSL root 50개: 작성자 0.930초, 부모 0.865초, James 0.833초, Popper 0.861초, 모두 exit0.
  부모의 첫 non-root 호출은 root 전용 harness 조건 때문에 실패했으며 위 결과와 구분한다.
- 새 input/audit은 각각 기존 경로의 `-r3`이며 root0700·네 파일0600·정확 해시를 확인했다.
- unit `kt-transport-parking-71a551ef-20261026-r3`, invocation `9147bd3bb50e462383a0944592dbe729`.
  05:00:47 UTC에 Manager global lock을 얻고 재개했다. r2 input/audit/unit은 보존했다.

r3는 첫 `approved-host-effect`에서 중단됐다. 후보 `validate-deploy-host.py` 내부의
`sudo -n ktdctl targets validate --json` 제한은 30초이며, 외부 Runner 기본 120초와 구분한다.
validator exit2 뒤 같은 process group의 후손이 약 5초 더 살아 있어 `child-descendants-unknown`으로
승격됐고, 05:01:25 UTC에 37.283초·child 종료 확인·`UNKNOWN_NO_PAUSE_PERFORMED`로 끝났다.
이때 기록된 `deadline_exceeded:true`를 외부 120초 초과라고 해석하지 않는다.

읽기 전용 재조회에서 PGID1761757 구성원은 0이고 unit MainPID0·exit1이었다. 다섯 역할의
ID/image ID/StartedAt은 r2 원본과 같고 모두 running/healthy/paused:false였다. 이 실행에서는
일정 중지·소스 staging·이미지 교체를 시작하지 않았다. r3의 builder flag false는 r2가 시작한
builder의 STOPPED 복원 완료를 뜻하지 않으며, 남은 책임은 r2 계보로 계속 추적한다.

최초 내부 예외는 validator의 generic exit2 처리 때문에 확정하지 못했다. 내부 30초 제한과
기존 약 28초 관측이 이번 시각과 가장 잘 맞지만 이를 원본 `TimeoutExpired` 증거라고 쓰지 않는다.
동일 Manager 읽기 전용 명령을 retry 없이 한 번 측정한 결과는 19.339초·exit0·`status:ok`였고
Transport→odroid→192.168.1.13 정합성을 확인했다. 이 관측의 외부 90초 제한은 배포 validator를
바꾼 것이 아니다. 공식 CLI에 deadline 조정 옵션이 없어, 실제 validator 소스의 30→60초 수정과
실패 폐쇄 회귀를 별도 코드 PR에서 검증한 뒤 새 후보로 배포하기로 했다.

## 검증 기한 수정과 빌더 원상복원

실제 수정은 [PR140](https://github.com/digitie/kor-travel-transport/pull/140)의
`d4166e86974f4f97dfdfbae6f107c1b399ff808a`다. Manager 기한 한 줄만 30→60초로 바꾸며
hostname15초·주소/registry/env·실패 폐쇄는 유지한다. 신규 세 회귀를 포함한 배포 계약은 WSL107개와
네트워크 없는 전용 Docker Compose107개를 통과했다. 문서의 최초 원인 확정 표현은 리뷰에서 고쳐
James/Popper가 최종 HEAD를 수용했다. push/PR의 backend·frontend·transport-admin 필수 CI는 모두
SUCCESS이며 optional live-e2e는 SKIPPED다. PR 전체 backend는1203통과·2건 건너뜀·2973.69초다.
06:06 UTC에 main `7f01b0133dad73843ce61444830b1020cfd32f0a`로 머지했고 이 새 SHA를 배포한다. 세부는
[전용 보고서](2026-10-26-host-validation-deadline.md)를 따른다.

빌더 원래 STOPPED 복원은 별도 작은 controller로 처리한다. 배포·일정 중지 기능은 없으며,
G→R 아래 실제 이전 자식 종료·소유 계보·정확 builder/registry/cgroup·현재 solve0·운영 역할과
보호 자료의 전후 불변을 확인하고 해당 builder의 `docker stop --time 30`만 한 번 호출한다.
정상 수집 worker를 0으로 강제하지 않는다. CS의 비계약 `RELEASE_SHA` 필수 조건은 제외하고,
CS exact ID/image/StartedAt·전체 Env 해시 불변과 backend/admin의 계약 SHA는 유지한다.

- cleanup SHA256: `72f126203e4dce197b5d230f2590c9fb2cbd8e4c8a5253db4ae551a6667e844b`.
- 비운영 WSL root37개: 작성자0.387초, 부모0.368초, James0.203초, Popper0.360초, 모두 exit0.
- 새 root0700/600 입력에서 같은 해시를 확인하고 unit `kt-transport-parking-builder-cleanup-20261026`을
  시작했다. invocation `186ee01af74b4848b6c6a9fe877585e9`는 G 획득 전 `ManagerMutationActiveError`로
  종료했다. MainPID0·exit1이며 새 source proof만 남고 실제 정리 명령·Docker stop은 실행하지 않았다.
- 기존 r2/r3 입력·원장·unit과 세 완성 이미지는 보존한다. cleanup의 90초 Manager 읽기 전용 조회는
  빌더 정리의 호스트 대조이며, 다음 배포의 공식 validator를 생략하는 수단이 아니다.

05:35:18 UTC의 `/proc/locks`에서 G의 실제 FLOCK 소유자는 root Python PID1778239였고,
cgroup은 `/system.slice/kt-weather171-build-20261026-r3.service`였다. 05:36:04 재조회에서도
05:07:19 시작한 해당 unit과 실제 docker/buildx 자손이 살아 있었다. stale 잠금으로 해석하거나
타 빌드를 중지하지 않고 정상 종료를 기다린다. 이후 Weather의 정식 교체로 바뀔 수 있는 foreign
컨테이너는 오래된 r2 상태로 되돌리지 않으며, 다음 cleanup의 G 안에서 얻은 fresh before/after로
보존하고 과거 기준과의 차이는 별도로 기록한다. Transport 역할·보호 파일·복구 자료는 계속 엄격히 확인한다.

05:54 UTC 이후 읽기 전용 관측에서 해당 Weather unit·기존 process group·cgroup 작업이 종료되고
G 소유자가 없음을 확인했다. Weather 앱의 배포 성공 여부는 이 관측의 범위가 아니다.
새 `cleanup-r2`는 같은 잠금 순서 아래 fresh 기준을 얻어 다음과 같이 정리를 완료했다.

- controller SHA256: `c59fe0a19a1ce07a363a1f743718d2f0458b0094d4d18f88efad23eaca1bc1ef`.
- WSL root40개: 작성자0.421초·부모0.390초·James0.210초·Popper0.394초 모두 PASS, 두 독립 최종 리뷰 PASS.
- unit `kt-transport-parking-builder-cleanup-20261026-r2`, invocation `f61bc6f186354b048daa4a5b38cd5a94`.
- 05:56:29.736620 UTC에 `BUILDER_ORIGINAL_STOPPED_RESTORED`, MainPID0·exit0으로 종료했다.
  Manager 읽기 전용 조회는26.989초·exit0, 정확한 소유 builder 한 번 중지는3.047초·exit0이었다.
- `child_known_ended:true`, 빌더 STOPPED 재확인, 일정 변경0건이다. 운영 다섯 역할·환경·복구 이미지·
  소스889항목과 fresh foreign53개가 전후 같았다. 과거 r2 foreign 기준 대비 추가1개는 별도 이력이며
  정리의 거부 조건으로 쓰거나 되돌리지 않았다. Transport instigator18개는 RUNNING이었다.

원래 r2 결과의 `builder_started_by_this_run:true`는 수정하지 않는다. 위 독립 원장이 남은 복원 책임을
완료한 증거다. PR140의 새 full SHA·새 archive·새 입력/원장/unit으로 정식 배포하며,
과거 세 이미지를 새 후보의 이미지라고 재명명하지 않고 실제 빌드 결과를 다시 확인한다.

## 새 후보 정식 실행

새 후보는 `7f01b0133dad73843ce61444830b1020cfd32f0a`다. 이전71a와 비교한 변경은
호스트 validator·그 회귀 테스트·전용 보고서의3파일이며 backend/app·frontend·packages는 같다.
새 clean Linux checkout의 canonical archive SHA256은
`8f2b174651fef47fd3793d179f451bb8b0eac7965de02be708c55262b6ee0c51`이며
PAX full SHA·918member·일반파일776개와 공식 세 셸 본문의 정확 해시를 확인했다.
backend의 테스트·scripts COPY 뒤 레이어는 달라지므로 과거 이미지의 이름만 새 후보로 바꾸지 않는다.

- controller SHA256: `5fd3c515da86bd7ff27d0b04d1e20b021fed73e1fa14d11cfe3f14279076b8ac`.
- helper SHA256: `80b19ebf1f2b22d27f665f2a0871298bd7ada23a2fc69242640faa9735e9ee47`.
- WSL root48개: 작성자1.062초·부모1.016초·Popper1.003초 및 James 독립 PASS.
  James 최초 non-root harness 실패는 root 재실행 PASS와 구분해 보존한다.
- 두 독립 코드 최종 P0/P1/P2는 없다. 준비 README의 과거 후보/44개 표기는 수정 후 두 검토자가 재확인했다.
- 새 root0700/입력3개0600과 정확 해시를 재확인했다. 업로드는 `parking-upload-7f01b013.2mmNK4`,
  입력과 원장은 각각 `parking-release-input-7f01b013-20261026`, `parking-release-7f01b013-20261026`이다.
- unit `kt-transport-parking-7f01b013-20261026`, invocation `173c79a3e0f048bfa83a50ee0525b746`.
  06:15:05 UTC에 G를 얻고 새 호스트 검증을 시작했다. 실행 전 fresh 관측에서 G는 비어 있고
  소유 빌더는 STOPPED, 다섯 Transport 역할은 healthy였다.

새 호스트 검증·NVMe·공식 관리자 preflight를 통과하고, source 백업과 fresh 기준을 보존했다.
이번 fresh foreign은52개이며 이전 cleanup 관측53개와 구분한다. 공식 staging은06:15:56 UTC에
exit0으로 끝났다. backend는06:16:00~06:20:37 UTC·276.825초, 공개 웹52.768초,
관리자40.819초로 세 빌드가 모두 exit0이었다.

06:22:19 UTC에 Transport 일정18개를 STOPPED로 검증한 뒤 활성run2개/worker4개의 자연 종료를
기다렸다. 06:23:37 UTC에 fresh 상태 백업10,476항목을 보존했다. 정방향 코드 서버 교체 뒤 상태
복사와 기존 이미지로 되돌린 뒤 같은 복사가 각각 exit1로 끝났다. 06:29:45 UTC의 최종 결과는
`UNKNOWN_PAUSE_RETAINED`, child 종료확인true·일정중지true·소유 builder RUNNING이다.
이 원본 결과를 배포 완료나 복구 완료로 고쳐 쓰지 않는다.

10월27일06:14 KST 읽기 전용 실측에서 기존a93 이미지의 다섯 역할은 모두 healthy였고,
소스·API·관리자 영수증도 a93으로 돌아왔다. Transport 일정18개는 STOPPED, 활성run과 실제CS
worker는0이다. 과거 배포가 소유한66 child PID/group/session 구성원도0이었다.
현재 코드 서버에는 `/opt/dagster`와 `/opt/dagster/state`가 모두 없고 `/opt`는 정상 root755이다.
원본 백업의 uid/gid/mode/hash10,476항목은 manifest와 정확히 같았다. 디스크248.6GB와 inode 여유도
있으며 rootfs는 읽기 전용이 아니다. 원 stderr가 보존되지 않아 최초 오류 문자열은 확정하지 않는다.
없는 부모를 생성하지 않는 Docker copy 동작을 검증하고, 새 독립 원장 아래 부모 준비·상태 검증·
원래 일정 복원을 먼저 수행한 뒤 수정된 배포 제어로 다시 전환한다.

## 10월27일 상태·수집 복구와 배포 재개

복구 제어기는 배포나 빌드를 하지 않는다. G→R 안에서 원래 실패한 자식의 종료·현재 Manager 승인·
NVMe·기존 소스889개·보호 환경·schema·다섯 이미지와 fresh 일정/worker 상태를 확인한다.
Transport 원래18개 RUNNING을 목표로 삼고 foreign 일정·컨테이너는 현재 상태를 보존한다.
없는 root 소유 부모만 생성한 뒤 상태를 복사하며, 원본10,476개 전체 검증과 기존 runtime 불변을
확인한 뒤 소유 builder STOPPED·원래 일정을 복원한다. 부분 복원 실패에는 다시 pause하고 UNKNOWN을 남긴다.

- 복구 controller: `4c33adb717c08f46b6a44cde2916606d0c867426dc964cc1ebd373ffc3b9fc17`.
  검토된 runner5fd3·helper80b 원문을 새 입력으로 재사용하며 원래 원장은 수정하지 않는다.
- WSL root20개: 작성자0.299초·부모0.265초·James0.277초·Popper0.277초 모두 PASS.
  Popper의 umask077 조건부 P2를 새로 만든 디렉터리에만 chmod0755하는 한 줄과 회귀로 해소했다.
  최종 두 리뷰에 잔여 P0/P1/P2가 없다.
- 격리 WSL Docker에서 missing-parent 복사 exit1, 실제 같은 경로 준비 코드와 umask077 아래 부모2개
  root755 생성, 복사 exit0 및 내용/uid/gid/mode 일치를 확인하고 소유 컨테이너를 제거했다.
- unit `kt-transport-parking-state-recovery-20261027`, invocation `edf2f9edba594b9fa714f9ee016f4437`.
  새 입력 `parking-state-recovery-input-7f01b013-20261027`과 audit `parking-state-recovery-7f01b013-20261027`을 쓴다.
  21:30 UTC에 경로 준비와 복사가 성공했고21:30:58 UTC에10,476개 전체 비교가 exit0이었다.
  21:31:52 UTC에 `OLD_STATE_AND_ORIGINAL_SCHEDULES_RESTORED`·MainPID0·exit0으로 종료했다.
  `state_verified`, `builder_stopped_verified`, `original_states_verified`, `child_known_ended`는 모두true,
  `instigators_paused:false`이며 deadline_unknown은false다. 기존다섯역할·보호자료·fresh foreign은 전후 같았다.

새 정식 배포 입력은 controller `d3c5c7ecfbfec9610983bb6652cb17baf487e62c792c276d27471d6593bb7042`,
helper80b이며 후보·archive·공식 셸 본문과 기존 제어 흐름은 같다. 부모를 root 소유·안전한
디렉터리인지 lstat로 검증하고, 원본과 일치하는 부분 상태만 허용한 뒤 복사한다.
기존48개와 신규10개를 합한 WSL root58개·실제 격리 Docker 복사·두 독립 리뷰가 통과했다.
부모1.422초·James1.411초·Popper1.466초이며 새 input `parking-release-input-7f01b013-20261027`에
root0700/입력3개0600·정확 해시로 설치했다. 복구 종료 확인 전에는 새 배포를 실행하지 않는다.

복구 성공과 fresh G 비어 있음·소유 builder STOPPED·다섯 역할 healthy를 다시 확인한 뒤
unit `kt-transport-parking-7f01b013-20261027`, invocation `6d06f744859a43a9abed4e087de899ac`를 시작했다.
새 입력·원장은 각각 `parking-release-input-7f01b013-20261027`, `parking-release-7f01b013-20261027`이다.
새 전환도 snapshot·state backup을 다시 만들며 원래 실패 결과를 덮지 않는다.

이 첫27일 전환은21:32:45 UTC에 기존7f01 rollback tag를 발견한 guard에서
`ABORTED_BEFORE_STAGING`으로 끝났다. 일정 미중지·빌더 미기동·child 종료이며 앱 교체는 없었다.
기존 태그를 덮지 않고 이번 실행의 저장소 이름만 `kor-travel-transport-rollback-20261027-r2`로
분리했다. 보존·복구 두 참조와 새 원장 경로 이외의 동작 변경은 없다. 읽기 전용 실측에서 원래
다섯 rollback image ID가 그대로이고 새 다섯 참조는 모두 없음을 확인했다.

최종 controller `c7f76efced4986121051caedf923b62ee594f3b2e729ff3e2b5ed359d3290bd1`와 helper80b는
부모58개1.422초·James58개1.404초·Popper58개1.372초 및 최종 두 독립 리뷰를 통과했다.
새 input/audit/unit은27일 이름 뒤 `-r2`를 붙이며, invocation `9e4bd4db177d446b939b3abd02156d9e`로
실행했다. 이전 원장·입력·이미지와 원래 복구 성공 기록은 그대로 보존한다.

이 새 실행은 과거 stage·instigator snapshot·state backup을 재사용하지 않았다.
최종 배포 결과는 문서 상단과 아래 실제 수용 기록을 따른다.

## 전환과 검증

- 별도 소유 빌드에서 기존 서비스를 유지한다. 과거 일정 snapshot을 재사용하지 않는다.
- Manager global mutation lock 다음 Transport release lock 순서를 유지한다.
- 교체 직전 Transport 일정의 원래 상태를 새로 기록하고, 이 location만 일시 중지한다.
- 대기·진행 중 run과 실제 worker가 모두 자연 종료된 뒤 공식 배포 절차로 교체한다.
- 새 health SHA·code-server 12306·location과 웹/API, 원래 instigator 상태 및 타 서비스 보존을 확인한다.
- 실제 공항주차장 네 뷰·분석 네 탭, 실제 항공편과 자연 수집 뒤 분석 캐시를 검증한다.

위 절차의 최종 배포 성공은 확인했다. 실제 수용 결과와 미해결 항목은 다음과 같다.

## 10월27일 실제 관리자 화면과 자연 통계 갱신

이 절의 시각은 별도 표기가 없으면10월26일 UTC(한국시간10월27일)다. 브라우저는 배포 영수증의 full SHA·고유 다섯 역할·image ID를
대조한 뒤 새 세션으로 검사했다. 인증과 기존 요금 계산 외 수집·설정 쓰기는 하지 않았다.

- Firefox1440과 Chromium375/1440에서 주차 네 뷰와 분석 네 탭을 실제 저장 자료로 확인했다.
  정보 버튼·Escape·Dagster 링크·과거7일 범위·요금 계산과 날짜 선택을 확인했다.
  Firefox375의 최초 분석은30,012ms 뒤504였다. 뒤1440 분석200/7,689ms와 Chromium375의
  200/7,824ms가 이 실패를 소급 통과로 바꾸지는 않는다.
- 격리 Firefox1440의 첫 달력 열기20→21은 임의 sleep이나 첫 응답 대기 없이 통과했다.
  과거 첫 opening UNKNOWN은 당시 기록으로 남기며 이번 새 성공과 구분한다.
  Firefox/Chromium320px·글자100/200%에서 날짜 셀44px·겹침/가림0과 Escape를 확인했다.
- Transport9경로×375/1440의 외곽·지도 높이·가로 넘침18건은 통과했으나 초기 map/fuel의
  데이터 대기 중 캡처는 상세 데이터 성공 증거가 아니다. 별도 Firefox는 실제 features 응답 뒤
  지도375/1440의 타일18/48개와 유가375/1440의30/48개 image200·WebGL2·줌 실클릭·출처 링크를 확인했다.
  모바일 유가지도는 최초 측정595px→다음565px의30px 변화를 원본 실패로 남겼다.
  새 세션에서 데이터200·폰트 준비·연속 두 프레임 안정 뒤 측정한 지도565px는 목록 왕복 후에도565px였다.
  주유소 선택은 카메라를 해당 장소로 옮기는 계약이다. 선택 이후 카메라 고정을 요구한 시험은
  제품 회귀로 해석하지 않으며 무선택 카메라 왕복과 구분한다.
  같은 원본의 detailOpened=false는 async count의 await 누락이었다. 실제 상세 DOM·44px 닫기와
  Escape가 열림을 입증하며 helper를 고쳤지만 원본 FAIL은 덮지 않았다.
- Firefox375 고속도로 roads429도 보존한다. 소스는 ITS worker 캐시의 차단 기한/일일 예산에서
  429를 반환하며 상류 실패는15분 backoff로 이어진다. 당시 Retry-After는 저장되지 않았으므로
  복원하지 않고, 단순히 연속 UI 시험이 원인이라고 단정하지 않는다.

실제 항공편은 기존 UI가 받은 김포27일 공개 DTO를 재사용했다. SDK 추가 조회는0회다.
365개는 묶인 마커 수,501개는 판매 편명 항목,609개는 결합 표시명을 포함한 검색 멤버 수다.
609개를 실제 항공편 수로 부르지 않는다. 공동운항 마커108개와 한국시간 운항 날짜 불일치0을
확인했다. 응답은 메모리 TTL 캐시이며 DB 영속 저장 증거가 아니다.

첫 자연 run `901d48dc-95ad-486f-9cc8-33cbc936ee3e`는22:02:15.787→22:13:29.887에
SUCCESS로 종료했다(한국시간07:02→07:13). 원본 CollectionRun3020은
22:04:13.609→22:04:39.038 success이고14공항44개가 저장됐다.
김포5개 관측의 observed_at은22:04:03, 대표 collected_at은22:04:18.539다.
김포 기본 캐시는0→24행(공항 전체+활성5주차장, 각각4지표)으로 증가했고
source_observed_at22:04:03/generated_at22:04:39.212를 대조했다.

이 첫 run의 시작은22:02:44 기준 DB 관측보다 먼저다. 이후 시작한 자연 run이라는 엄격한
두 관측 조건의 최종 after로 바꾸지 않는다. 원본 수집은 약25초지만 전체 분석을 순차 계산하고
commit하는 데 약9분이 더 걸렸다. 실제 job 종료 때 캐시 watermark는 약8분51초가 지나
10분 만료에 근접했다. 새 적재 확인과5분 주기·캐시 성능 수용은 별개이며 개선을 진행한다.

별도22:26:29.903의 after에서 기준 관측 이후 시작한 자연 run
`c8084888-0767-437b-af1e-7c9ad64adee1`의 SUCCESS와 schedule 태그를 대조했다.
run은22:16:10.757→22:24:04.224(473.467초), CollectionRun3023의 원본 수집은15.505초다.
김포5개 새 적재와6scope×4지표 갱신을 확인했고 대표 collected_at은21:37:51.186→22:17:15.541,
캐시 generated_at22:17:28.999/source_observed_at22:17:03 및 payload watermark가 일치했다.
엄격한 두 관측의 갱신 증거는 PASS지만 원본 이후 파생 구간 약395초는 여전히5분을 넘는다.
이 증거로 성능 task를 닫거나 최초 모바일504를 통과로 바꾸지 않는다.
원본 before/after hash는 `cache-strict-summary-b56fe2d8-e375-4df5-9ffd-c60003014bfd.json`에 연결했다.

주요 원본은 `/var/tmp/codex-live-ui-20261026/runs/7f01b0133dad73843ce61444830b1020cfd32f0a/`
하위의 실행별 UTC·UUID 폴더다. 최초 분석1440의 메타데이터 파일에는 full DTO와 정확한
HTTP 수신 완료 시각이 없으며 뒤늦게 복원하지 않았다. 후속 집중 시험은 별도 파일로 보존한다.
모든 실제 검증을 하나의 PASS로 묶지 않는다. 공식 요금 원문 대조·물리 기기·전체 소비자·
철도/유가 후속, 약15시간 수집 공백과 성능 초과는 열린 상태다.

22:16의 집중 Firefox375 분석은 요청22:16:12.745→본문 수신 완료22:16:18.772에
HTTP200/6,028ms였고7/8/20/1,009개를 화면과 대조했다. full DTO와 후보/API SHA를 새로
보존했다. time_series.generated_at22:16:17.094260은 첫 캐시의22:04:39와 다르지만
이 DTO만으로 캐시 미적중 경로를 확정하지 않는다. 최초504를 덮지 않고 성능 목표 초과도 남긴다.

초기 종료 helper의 Origin 없는 APIRequestContext logout은403이었다. 성공한 정리로 세거나
제품 logout 실패로 단정하지 않는다. 마지막 브라우저 same-origin 확인에서는 로그인200→
logout303과 쿠키1→0을 확인했다. 소유13runner/13child 종료·n150 작업UUID 잔여0을
`/var/tmp/codex-live-ui-20261026/cleanup-final-7f01.json`에 남겼다. 다른 작업 중지와 kill은0이다.
전체 실제 QA 해석은 같은 디렉터리의 `2026-10-27-transport-7f01-live-ui-acceptance.md`를 따른다.

Weather는 사용자 지시로 진행 중 수집의 자연 종료 전 이미지 교체를 하지 않는다.
Weather의 실제375px 지도615px와 상세 오버레이는 확인했지만 마커 배치504와
미확인 날씨를 구름으로 표시하는 결함을 발견해 별도 소스 수정 중이다.
Transport 배포 완료를 Weather 새 후보의 배포·전체 기능 완료로 확대하지 않는다.
