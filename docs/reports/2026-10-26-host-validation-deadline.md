# 배포 호스트 검증의 Manager 응답 기한 보완

## 증상과 범위

2026-10-26 공항 주차장 통합 후보 `71a551ef7fa29957be018294363063e1870be011`의 배포를 진행하던 중,
호스트 검증이 exit2로 종료됐다. `scripts/validate-deploy-host.py` 내부의
`sudo -n ktdctl targets validate --json` 기한은 30초이며 바깥 명령 기한은 120초다.
validator는 내부 예외를 같은 exit2로 처리하므로 최초 오류가 `TimeoutExpired`였는지는 확정하지 못했다.
당시 소요 시각은 내부 30초의 여유 부족과 정합적이지만 이를 확정 원인으로 해석하지 않는다.
배포 담당자가 전달한 기록에는 종료 후 후손 프로세스가 약5초 남아 `UNKNOWN`으로 보존됐고,
운영 컨테이너는 교체되지 않았다. 별도로 제한된 읽기 전용 동일 명령은 19.339초·exit0이었다.
기존 [유가 동시성 배포 기록](2026-10-23-fuel-concurrency-rollout.md)에서도 Manager CLI27.99초·전체 검증28.04초가
걸린 이력이 있다.
이는 응답 시간 변동의 근거이며 대상 호스트나 registry 계약 변경을 뜻하지 않는다.

실제 배포 실행·읽기 전용 계측은 배포 담당자의 별도 증적이며, 이 수정 작업에서 운영 SSH·DB·외부 API를
호출하거나 배포를 실행하지 않았다. 이 문서의 단위/컨테이너 검증을 실제 운영 배포 성공으로 해석하지 않는다.

## 수정

- Manager 호출의 `subprocess.run(..., timeout=30)`을 `timeout=60`으로 변경한다.
- `hostname -I`의 15초 기한, canonical IPv4·원격 할당 주소·Manager의 Transport 대상·읽을 수 있는 환경 파일
  검사는 유지한다. Manager 명령·옵션과 1MiB 응답 제한도 유지한다.
- 시간 초과·명령 실패·잘못된 JSON이나 registry 불일치는 계속 exit2로 거절한다.
  Manager의 stdout/stderr와 입력값은 오류 메시지에 다시 출력하지 않는다.
- UI·API·provider SDK·DB·Compose·배포 셸 본문은 변경하지 않는다.

## 검증

실제 45초나 60초를 기다리지 않고 `subprocess.run` 대역으로 응답 기한을 검증한다.
45초 후 정상 응답하는 상황은 기존30초 코드에서 거절되고 수정한60초 코드에서 통과한다.
호출 인자 전체를 비교해 Manager60초와 hostname15초를 확인한다. 각 명령의 `TimeoutExpired`는 exit2와
고정 오류 문구만 반환하며 이후 환경 파일 접근을 진행하지 않는지 검증한다.

| 실행 | 결과 | 범위 |
|---|---|---|
| WSL 수정 전 집중 회귀 | 1실패·2통과, exit1 | 45초 응답의 기존 거절 재현·두 명령 시간 초과 |
| WSL 수정 후 배포 계약 | 107통과, exit0, 9.07초 | 호스트·원격 가드·NVMe·공용 DB·운영 포트의 기존 계약5파일 |
| WSL Docker Compose 집중 검증 | 107통과, exit0, 8.81초 | 같은5파일, 독립 소스·네트워크 없음·읽기 전용 소스 mount |

WSL은 일반 사용자 `digitie`와 기존 Python3.12 테스트 환경을 사용했다. Docker는 전용 Compose project
`codex-host-validator-20261026`의 일회성 `run --rm --no-deps`로 실행했다.
이미지 `sha256:87a15433fac062824b926e2631d1d4cdaf543c2014581d9552a671ba9d4b3bb8`의 pytest를 재사용하되,
테스트와 검사 대상 스크립트는 모두 이번 소스를 읽었다. Docker의 `--noconftest`는 애플리케이션·DB fixture를
로드하지 않도록 한 것으로, 배포 계약5파일 자체와 각 assertion은 WSL 실행과 같다.
증적은 WSL `/var/tmp/codex-host-validator-tests-20261026.R8EPiC/`의 `red.log`, `red.exit`,
`green.log`, `green.exit`, `docker.log`, `docker.exit`, `compose.yml`에 보존한다.

첫 WSL 명령 전달 시 임시 경로의 셸 변수가 유실돼 `/red-tmp` 권한 오류3건이 발생했다.
이는 기능 회귀 결과로 세지 않았으며 소유한 `.sh` 실행기로 경로를 고정한 뒤 위 RED/GREEN을 다시 실행했다.

## 인계

소스 수정의 CI와 독립 적대적 리뷰2명이 끝난 뒤 머지된 새 후보에서 정식 배포를 재개한다.
이 변경으로 Manager 검증을 생략하거나 이전 `UNKNOWN` 실행과 중첩 배포하지 않는다.
후손 프로세스 종료, 전역/릴리스 잠금, Transport instigator 중지·자연 drain·원상 복구와 실제 운영 수용은
[현재 배포 런북](../runbooks/deployment.md) 및 배포 담당자의 최종 기록을 따른다.
