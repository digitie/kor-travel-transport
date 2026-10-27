# 공식 자식의 사전 빌드 handoff 검증

## 결과와 범위

기준 main `5c823c49030efd83a8839064dde15f1d5993192f`에서 공식 backend 자식의
재빌드·1800초 drain과 관리자 자식의 `up --build`를 우회하지 않고 별도 strict
`deploy-prebuilt` 계약으로 닫았다. 일반 배포와 prepare는 기존 경로를 유지한다.
[입력·복구·남은 launch 경합 설계](../design/2026-10-27-prebuilt-deploy-handoff.md)를 따른다.
운영 SSH/HTTP/Docker·일정·DB 변경, merge, 실제 배포는0이다. 제품 app·UI·SDK·의존성은 변경하지 않았다.

이전 r2 Popper 보고서는 공식 자식이 새 busy 실행을 만나도15초 sleep에 들어가는
순수 대역 재현을 제시했다. 그 보고서 bytes SHA-256은
`ebfe7db53eaee18a0aee7468c4ebfedc0845961d7a610b0672dd1c3312d03c4f`다.
기존 준비본·과거 완료 증거를 수정하거나 이번 배포 완료로 재사용하지 않았다.

## 실행한 검증

새 회귀를 먼저 실행해 helper 부재22오류와 strict 분기 부재1실패를 확인했다.
구현 후 기존 배포 식별자·호스트·저장소·공유 DB 계약을 함께 실행했다.

| 환경 | 실제 결과 | 범위 |
|---|---|---|
| WSL2 Ubuntu-26.04 | **158 passed**,8.85초 | 새 strict 회귀와 기존 배포 회귀5개 파일 |
| WSL2 Docker Compose | **157 passed,1 skipped**,8.70초 | 같은 소스 read-only mount, network none·Docker socket 없음 |
| 합성 state 계량 | 12,000×128B 파일,3회 **0.3122/0.2771/0.2686초** | WSL `/tmp`의 helper 순회; 운영 NVMe 성능 증거 아님 |

집중 명령은 `uv run --with pytest --with pytest-asyncio --no-project python -m pytest
--noconftest -p no:cacheprovider` 뒤에 `backend/tests/test_deploy_prebuilt_handoff.py`,
`test_deploy_prod_remote_guard.py`, `test_deploy_host_guard.py`, `test_deploy_storage.py`,
`test_shared_db_deploy_contract.py`를 명시했다. app conftest·PG를 쓰지 않는 배포 대역 검사다.
Docker도 `docker compose run --rm --no-deps -T backend`로 같은 파일만 실행했다.

Docker는 기존 로컬 image
`sha256:f57361035956794e678151ce377b75d46ea575ca92a64751cfef725eff88501a`를 재사용했다.
첫 실행23실패는 기존 대역 PATH `/usr/bin:/bin`에서 이미지의 `/usr/local/bin/python3`를
못 찾은 환경 차이였다. 폐기성 검증 컨테이너 안에만 `/usr/bin/python3` symlink를
만들어 해결했다. 임시 runner의 CRLF로 pytest 인자가 잘못 전달된1회도 LF로 고쳤다.
남은1 skip은 기존 `test_deploy_host_guard.py`의 rsync 실행 파일 부재 조건이며 WSL에서는 통과했다.

순수 회귀는 run 다섯 상태, origin/tag 모호성·1000건 잘림, 실제 worker, 일정/외부
catalog 변경, 다른 CID, image/schema/head 불일치, 같은 bytes 재작성·추가 후 삭제,
state 순회 중 새 run/worker, receipt hash·권한·hardlink·소유권, strict 실패 시 sleep·
up·기본 fallback·자식 rollback0, 다음 일반 배포의 strict 이전 이미지 검산을 포함한다.
관리자는 baked 전체 SHA·두 image ID·arm64와 실패 시 build/up0을 별도 검사한다.

## 고정 소스 SHA-256

아래는 LF 원본 bytes다. 후속 controller는 최종 Git archive와 이 원본의 계보를
다시 고정하며, 이 문서가 과거 archive의 승인 hash를 자동 갱신하지 않는다.

| 파일 | SHA-256 |
|---|---|
| `scripts/deploy-prod-remote.sh` | `b58c3288b5f0c0a07bbd171889f80b833456c4ee7734a212768454430d7bdd1c` |
| `scripts/deploy-transport-admin-prod.sh` | `81ddeaa134962381aad527207375dbf4d64de6e678d627a9b179e35f76d98a09` |
| `scripts/verify-prebuilt-handoff.py` | `5e1eeaf6414e8bbc0bcb0bbac6d0993b7f4ff90ae055d235ec6fd8673e957049` |

## 인계와 미검증

새 정확 candidate의 CI와 독립 James/Popper 검토는 부모가 정산한다. 실제 운영에서
receipt를 만드는 새 controller, 원본 fingerprint 전후 검산, 자식 실제 종료 이후
복구, state가 변한 채 교체0으로 거절된 경우의 현재 상태 보존도 부모의 필수 계약이다.
이전 제품 전체 테스트나 UI 수용을 새 운영 배포 증거로 확대하지 않는다.
최종 probe→Compose launch는 원자적 fence가 아니며 이 잔여 경합은 남는다.
