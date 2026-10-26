# 2026-10-26 공항 주차장 통합 릴리스 빌드·배포

상태: 세 이미지 빌드 성공 뒤 `-r2`는 마운트 순서 비교, 수정본 `-r3`는 호스트 검증 단계에서 교체 전에 중단됐다. 필요한 소스 수정 PR140은 전체 필수 CI와 두 리뷰 후 머지됐고 새 후보를 준비한다. 별도 정리로 빌더의 원래 STOPPED 상태는 복원했다. 아직 운영 교체 성공을 주장하지 않는다. 사용자가 통합 main의 빌드 후 배포를 승인했다.

## 후보와 기존 운영

- 후보: `71a551ef7fa29957be018294363063e1870be011`. 제품 기준 `1e50dbc`와 backend/frontend/packages가 같고 PR137은 문서만 변경했다.
- 기존 운영: API와 code-server의 `a93dfba27283224e1cf091865f2c08d40cdd9dc3`, 관리자·공개 웹·gateway를 포함한 다섯 역할이 healthy였다.
- Manager `targets validate --json`의 대상은 `odroid`, 주소는 `192.168.1.13`이다.
- 앱·중앙 환경·Docker·staging의 실제 저장 장치는 NVMe이며 사전 점검의 가용 디스크는 252GiB다.
- 공용 Dagster 1.13.24와 세 location이 정상이고 공용 daemon·PostgreSQL이 running/not-paused였다.
- 운영 후보 사이에 Compose·배포 스크립트·Alembic의 의미 변경은 없다. 운영 파일 63개는 CRLF, 후보 Git archive는 LF여서 바이트가 달랐으며 CRLF를 LF로만 바꿔 대조한 결과 나머지 차이는 0이었다. 공식 배포 `.sh` 원문은 바이트도 같았다. 의존성 변경은 검증한 공항 SDK pin을 포함한다.

사전 점검 원장은 WSL `/var/tmp/codex-transport-release-20261026.GDf0xA/preflight.json`에 보존했다.
비밀 환경 내용은 보고서에 복사하지 않는다. 아래 항목은 실제 실행 뒤 결과를 정산한다.

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

## 빌드 진행

운영 다섯 역할을 유지하면서 다음 순서로 이미지를 빌드한다. 시각은 UTC다.

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
`.release-sha`·`.admin-release-sha`도 기존 `a93dfba`와 일치했다. staged marker는 없었다.
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

## 전환과 검증

- 별도 소유 빌드에서 기존 서비스를 유지한다. 과거 일정 snapshot을 재사용하지 않는다.
- Manager global mutation lock 다음 Transport release lock 순서를 유지한다.
- 교체 직전 Transport 일정의 원래 상태를 새로 기록하고, 이 location만 일시 중지한다.
- 대기·진행 중 run과 실제 worker가 모두 자연 종료된 뒤 공식 배포 절차로 교체한다.
- 새 health SHA·code-server 12306·location과 웹/API, 원래 instigator 상태 및 타 서비스 보존을 확인한다.
- 실제 공항주차장 네 뷰·분석 네 탭, 실제 항공편과 자연 수집 뒤 분석 캐시를 검증한다.

이 문서는 아직 운영 배포 성공·실제 새 항공편·캐시 성능·Firefox 미확정 해소를 주장하지 않는다.
