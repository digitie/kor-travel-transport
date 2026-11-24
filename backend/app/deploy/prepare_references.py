"""배포 직후 새 code-server 이미지에서 기준정보 본문(ADR-016 artifact)을 준비한다.

입력 revision에 release_sha가 들어가 배포마다 모든 본문이 무효가 된다(WLH-03·MC-07). 다음 공항 수집의 준비 step은
code-server 냉기동·schedule tick·공항 수집 뒤에야 도므로, 그 사이 Map 첫 페이지가 요청 안에서 전체를 구성한다.
Dagster run을 새로 띄우지 않고(공용 run 큐·'reference' run_group 대기 p95 10~50분) 같은 준비 함수를 새 code-server
컨테이너에서 직접 부른다.

    docker exec <code-server> python -I -B -m app.deploy.prepare_references --expect-release-sha <API health release_sha>

- 준비 전에 이 컨테이너의 release_sha(입력 revision에 들어가는 값)가 서빙 중인 API의 값과 같은지 본다. 다르면
  API가 읽지 않을 revision의 본문을 만들고 head를 옛 값으로 되돌리게 되므로 준비하지 않는다(종료 코드 4).
- Map이 읽는 철도역·여객선 본문만 준비한다(bus·parking/current는 소비자가 없고 5분 공항 수집의 준비가 맡는다).
  준비 뒤 제한 정리(만료 handle → 미사용 본문)도 한다. 전체 예산은 120초(`--timeout-seconds`보다 10초 짧게 줄인다).
- Dagster run 밖이라 run_group 상한·수집 owner가 없다. 5분 공항 수집의 준비와 같은 본문을 두고 겹칠 수 있지만,
  겹친 종류는 `busy`(실패 아님)로 끝나고 어느 쪽도 실패하지 않는다(`prepare_reference_exports`).

stdout에는 종류별 결과 JSON 한 줄만 낸다(kind·status·duration_ms·error_type 등, DSN·토큰 없음). 종료 코드:

- 0 = 대상 종류를 모두 준비·재사용했다(또는 Map current 비활성 `disabled`).
- 5 = 고장은 아니지만 본문이 다 준비되지는 않았다 — 원천 미완결(`not_ready`)·다른 준비와 경합(`busy`)·예산 소진(`deferred`).
  다음 공항 수집의 준비나 첫 Map 페이지가 만든다.
- 1 = 일부·전체 실패(`partial_success`·`failed`)·시간 초과(`timeout`)·실행 오류(`error`).
- 4 = release_sha 불일치로 건너뜀(`release_mismatch`).
어느 쪽이든 배포는 실패시키지 않는다(wrapper가 경고만 남긴다).
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from time import monotonic

_KIND_FIELDS = ("kind", "status", "duration_ms", "item_count", "source_status", "error_type", "sqlstate", "reason")
EXIT_OK, EXIT_WARN, EXIT_RELEASE_MISMATCH, EXIT_INCOMPLETE = 0, 1, 4, 5
_RELEASE = re.compile(r"^[0-9A-Za-z._-]{1,80}$")
#: 바깥 상한(--timeout-seconds) 안에서 준비 예산을 끝내는 여유.
_TIMEOUT_RESERVE_SECONDS = 10


def _summary(result: dict) -> dict:
    summary = {key: result[key] for key in ("status", "prepared", "reused", "busy", "deferred", "failed") if key in result}
    summary["kinds"] = [{key: row[key] for key in _KIND_FIELDS if key in row} for row in result.get("kinds") or []]
    gc = result.get("gc")
    if isinstance(gc, dict):
        summary["gc"] = {key: gc[key] for key in ("expired_handles", "unused_artifacts", "duration_ms", "busy", "skipped")
                         if key in gc}
        if isinstance(gc.get("error"), dict):
            summary["gc"]["error_type"] = gc["error"].get("error_type")
    return summary


def _exit_code(summary: dict) -> int:
    status = summary.get("status")
    if status == "disabled":
        return EXIT_OK
    if status == "success" and not summary.get("busy") and not summary.get("deferred"):
        return EXIT_OK
    if status in {"success", "deferred", "not_ready"}:
        return EXIT_INCOMPLETE
    return EXIT_WARN


def _emit(summary: dict, started: float) -> None:
    summary["duration_ms"] = round((monotonic() - started) * 1000)
    print(json.dumps({"event": "reference_prepare_after_deploy", **summary}, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="배포 직후 기준정보 본문 준비(best-effort)")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--expect-release-sha", required=True,
                        help="서빙 중인 API /health의 release_sha. 이 컨테이너의 값과 다르면 준비하지 않는다.")
    args = parser.parse_args(argv)
    if not 30 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds는 30~1800이어야 합니다")
    if not _RELEASE.fullmatch(args.expect_release_sha):
        parser.error("--expect-release-sha 형식이 올바르지 않습니다")
    # 무거운 앱 모듈은 인수 검증 뒤에만 읽는다.
    from app.core.config import get_settings
    from app.services.reference_export_preparation import (
        MAP_EXPORT_KINDS,
        PREPARE_TOTAL_BUDGET_SECONDS,
        prepare_reference_exports_for_settings,
    )

    started = monotonic()
    settings = get_settings()
    local_release = settings.release_sha or "unknown"
    if local_release == "unknown" or local_release != args.expect_release_sha:
        # 두 값은 git SHA(비밀 아님)다. 불일치는 code-server만 롤백됐거나 RELEASE_SHA 없이 띄운 경우다.
        _emit({"status": "release_mismatch", "code_server_release_sha": local_release[:80],
               "api_release_sha": args.expect_release_sha}, started)
        return EXIT_RELEASE_MISMATCH
    budget = min(PREPARE_TOTAL_BUDGET_SECONDS, args.timeout_seconds - _TIMEOUT_RESERVE_SECONDS)
    try:
        result = asyncio.run(asyncio.wait_for(
            prepare_reference_exports_for_settings(settings, kinds=MAP_EXPORT_KINDS, total_budget_seconds=budget),
            timeout=args.timeout_seconds,
        ))
    except TimeoutError:
        summary: dict = {"status": "timeout"}
    except Exception as exc:  # noqa: BLE001 - 원문(DSN 등)을 출력하지 않는다.
        summary = {"status": "error", "error_type": type(exc).__name__}
    else:
        summary = _summary(result)
    _emit(summary, started)
    return _exit_code(summary)


if __name__ == "__main__":
    sys.exit(main())
