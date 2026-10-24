# 오피넷 개선 일괄 배포 인계

## 사용자 지시와 배포 경계

사용자가 2026-10-24 배포를 대기하고 다른 에이전트가 일괄 배포하도록 지시했다.
이 작업에서는 운영 staging·빌드·컨테이너·스케줄·센서·공용 daemon을 변경하지 않았다.
로컬 Linux 릴리스 체크아웃과 검증 이미지만 준비했다. 운영 적용·전국30분 실측은 미완료다.

제품 변경은 [Transport PR123](https://github.com/digitie/kor-travel-transport/pull/123),
최종 CI·리뷰·머지 여부도 같은 PR을 정본으로 확인한다. 코드 후보는
`7d254ccf879881e19d692e48a6fe96a91a2bcfae`이고 backend tree는
`a8cbf813bea3469d7d16a5fb6644eaae6d8c4db7`다. 후속 문서 변경과 구분한다.
일괄 배포할 때는 PR123 머지 결과와 그 뒤 승인된 다른 변경을 포함한 최신 후보를 사용한다.
이 후보는 main50537f6의 npm 보안 갱신을 포함한다.

Provider는 `f58a879676f8d2c6d8de26e3daaf7eb154fd9ad2`로 고정했다.
[PR24](https://github.com/digitie/python-opinet-api/pull/24)의 체크포인트,
[PR25](https://github.com/digitie/python-opinet-api/pull/25)의 조회 최적화,
[PR26](https://github.com/digitie/python-opinet-api/pull/26)의 작성자 경합 구분,
[PR27](https://github.com/digitie/python-opinet-api/pull/27)의 캐시·종료 보완은 머지됐다.
클릭·선택별 독립 무작위 지연은 사용자 최종 요청의 **150~850ms**이며 평균500ms다.

## 설치할 항목

- 현재 [배포 런북](../runbooks/deployment.md)과 ADR-014를 따른다. Manager 정본의
  Transport 대상·NVMe 저장·공용 Dagster 버전을 확인한다. 공용 daemon은 RUNNING을 유지한다.
  Manager global lock 다음 Transport release lock 순서를 지키고 다른 배포와 겹치지 않는다.
- API와 Dagster code-server는 같은 후보 이미지를 사용한다. `pyproject.toml`·`uv.lock`의
  provider SHA와 이미지에 설치된 VCS commit을 대조한다. 같은 패키지 버전이라는 이유만으로
  이전 검증 이미지의 provider가 남아 있지 않은지 확인한다.
- API·code-server에 `OPINET_CHECKPOINT_PATH=/app/collector-state/opinet.sqlite3`와 동일한
  `opinet-checkpoints:/app/collector-state` named volume을 적용한다. volume 실제 저장 장치도
  NVMe인지 확인한다. 파일 하나만 공유하지 않고 잠금·SQLite 부속 파일을 포함한 디렉터리를 공유한다.
- 이 기능 자체는 PostgreSQL migration을 추가하지 않았다. 일괄 배포에 포함된 main의
  schema0030~0033 적용 여부는 운영의 현재 revision과 대조해 별도로 처리한다.
- Transport의 원래 schedule·sensor 상태를 저장하고 해당 location만 일시 중지한다.
  queued/run과 실제 worker의 자연 종료를 모두 확인한 뒤 전환하고 원래 상태를 복원한다.
  공용 DB·daemon·다른 프로젝트 컨테이너를 함께 재생성하지 않는다.

## 마지막 읽기 전용 운영 확인

2026-10-24 10:38 KST 기준 기존 run1885는08:04:24~10:31:46에 성공했다. 마지막 원천
성공은10:27:19 KST이며10:40 KST의 실제 TCP fuel-stations export는HTTP200·items1,
failed/stale/last_attempt_failed=false였다. 새 후보의 효과로 해석하지 않는다.

11:33 KST에는 실제 API·CS가 `rel-e01f8e9c1292`, 공유 checkout의 staged/release가
`50537f6d8ee1e7b9883017e6845378bec75508b9`였다. 이후 다른 사전 빌드의 release lock도
관찰했다. 이 차이만으로 배포 실패라고 단정하지 않는다. 당시 API·CS는 healthy였다.

Transport instigator17개는 모두 STOPPED, 활성 run·worker는0이었다. **원래 상태 snapshot을
발견하지 못했으므로 의도한 중지인지 배포 잔재인지 미확정이다.** 이 작업에서 중지하거나
임의로 RUNNING으로 복원하지 않았다. 일괄 배포 담당자는 자신이 보유한 원래 snapshot과
현재 작업 소유권을 확인해야 한다. 오래된 이 관측을 새 배포의 drain 증거로 재사용하지 않는다.

## 재개와 배포 후 수용

- 체크포인트를 삭제해 재시작하지 않는다. 미완료는 완료 지역·차감한 요청 예산을 보존하며
  미완료부터 진행한다. 완료 결과는 외부 통신 없이 저장부터 재개한다. DB commit 이후에만
  소비 완료를 기록한다. 과거 실패 run1645의 롤백된 메모리는 새 파일로 복원할 수 없다.
- 기존8시간 간격과 요청 예산을 유지한다. 저장 재개는 기존 예약을 임의 연장하지 않는다.
  운영 수용을 위해 예약·최근 실행 제한을 우회한 강제 전국 수집을 추가하지 않는다.
- pending 확인 직후 생긴 실제 작성자 경합도 실패로 기록하지 않는다. 외부 요청이 없던
  자기 claim만 이전 상태로 되돌리고, 타인이 변경한 성공·오류·예약은 보존한다.
  완료 checkpoint를 전달받기 전 취소/오류가 나도 이후 다른 실행이 확정한 성공을 덮지 않는다.
  unhealthy busy의 실패 설명·metadata에도 `collector_busy`를 남긴다. in-process busy는
  기존 예약을 유지하면서 기본 수집 간격 이상의 대기를 적용한다.
- API health의 정확한 release SHA, CS의 같은 이미지·gRPC12306·공용 Dagster 버전,
  양쪽 체크포인트 경로·동일 volume·NVMe 저장을 확인한다.
- 정상 예약 실행의 실제 collection run·원천 성공 시각·주유소/유가 건수·최신 가격과
  export HTTP200을 확인한다. Dagster SUCCESS나 오래된 정상 데이터만으로 새 수집 성공을
  판단하지 않는다. 기존 미수집/실패 원천의 unhealthy skipped는 명시적으로 실패한다.
- 가린 INFO의 지역·탭 진행과 `selection`·`response`·`results` 누적 시간을 확인한다.
  전국 시작~완료를 실측하기 전에는30분 목표 달성으로 보고하지 않는다. 조작1150회 가정의
  랜덤 대기 평균은575초이며 시작·탐색120초를 더하면 검색460회당 나머지 평균2.4초가 필요하다.

## 검증 근거

Provider f58a879는 WSL355 PASS/4 live SKIP·coverage93.96%·mypy20파일·CI5개 PASS,
실제 Chromium29개와 James/Popper 최종 독립 재리뷰를 통과했다. 정리 상한과 원래 취소·
인증·요청 제한 오류 보존을 검증했다. 신규 경합 보완의 앱 집중 SQLite141·PostgreSQL141 PASS다.
직전361후보는 PostgreSQL128·Docker128·격리 실제 UI12 PASS, uv lock check PASS다.
프론트엔드 WSL130·Docker130 및 두 build도 통과했다. 새 후보 PG·Docker·UI 결과는 PR123에서 확인한다.

전체 앱 회귀·최종 CI·격리 UI·앱 공식 독립 리뷰의 최종 결과는 PR123에서 확인한다.
이전 c23 후보의 장기 전체 회귀 결과를 최종 SHA 전체 통과로 합산하지 않는다.
[상세 점검](2026-10-24-opinet-resume-review.md)에 재현·수정·검증 한계를 남겼다.
격리 PostgreSQL 합성40000행의 저장13.531초·동일 결과 재개0.026초는 외부 수집 없는
저장 경로 검증이며 운영 수집 시간의 증거가 아니다.
