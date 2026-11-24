"""배포 직후 새 code-server 이미지에서 기준정보 본문(ADR-016 artifact)을 준비한다.

입력 revision에 release_sha가 들어가 배포마다 모든 본문이 무효가 된다(WLH-03·MC-07). 다음 공항 수집의 준비 step은
code-server 냉기동·schedule tick·공항 수집 뒤에야 도므로, 그 사이 Map 첫 페이지가 요청 안에서 전체를 구성한다.
Dagster run을 새로 띄우지 않고(공용 run 큐·'reference' run_group 대기 p95 10~50분) 같은 준비 함수를 새 code-server
컨테이너에서 직접 부른다.

    docker exec <code-server> python -I -B -m app.deploy.prepare_references --expect-release-sha <API health release_sha>

- 준비 전에 이 컨테이너의 release_sha(입력 revision에 들어가는 값)가 서빙 중인 API의 값과 같은지 본다. 다르면
  API가 읽지 않을 revision의 본문을 만들고 head를 옛 값으로 되돌리게 되므로 준비하지 않는다(종료 코드 4).
- Dagster run 밖이라 run_group 상한·수집 owner가 없다. 5분 공항 수집의 준비와 같은 본문을 두고 겹칠 수 있지만,
  겹친 종류는 `busy`(실패 아님)로 끝나고 어느 쪽도 실패하지 않는다(`prepare_reference_exports`).

stdout에는 종류별 결과 JSON 한 줄만 낸다(kind·status·duration_ms·error_type 등, DSN·토큰 없음).
종료 코드 0 = 모든 종류를 준비·재사용·경합(또는 원천 없음·비활성), 1 = 일부·전체 실패·시간 초과,
4 = release_sha 불일치로 건너뜀. 어느 쪽이든 배포는 실패시키지 않는다.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from time import monotonic

_KIND_FIELDS = ("kind", "status", "duration_ms", "item_count", "source_status", "error_type", "sqlstate", "reason")
EXIT_OK, EXIT_WARN, EXIT_RELEASE_MISMATCH = 0, 1, 4
_RELEASE = re.compile(r"^[0-9A-Za-z._-]{1,80}$")


def _summary(result: dict) -> dict:
    summary = {key: result[key] for key in ("status", "prepared", "reused", "busy", "failed") if key in result}
    summary["kinds"] = [{key: row[key] for key in _KIND_FIELDS if key in row} for row in result.get("kinds") or []]
    gc = result.get("gc")
    if isinstance(gc, dict):
        summary["gc"] = {key: gc[key] for key in ("expired_handles", "unused_artifacts", "duration_ms", "busy") if key in gc}
        if isinstance(gc.get("error"), dict):
            summary["gc"]["error_type"] = gc["error"].get("error_type")
    return summary


def _emit(summary: dict, started: float) -> None:
    summary["duration_ms"] = round((monotonic() - started) * 1000)
    print(json.dumps({"event": "reference_prepare_after_deploy", **summary}, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="배포 직후 기준정보 본문 준비(best-effort)")
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--expect-release-sha", required=True,
                        help="서빙 중인 API /health의 release_sha. 이 컨테이너의 값과 다르면 준비하지 않는다.")
    args = parser.parse_args(argv)
    if not 10 <= args.timeout_seconds <= 1800:
        parser.error("--timeout-seconds는 10~1800이어야 합니다")
    if not _RELEASE.fullmatch(args.expect_release_sha):
        parser.error("--expect-release-sha 형식이 올바르지 않습니다")
    # 무거운 앱 모듈은 인수 검증 뒤에만 읽는다.
    from app.core.config import get_settings
    from app.services.reference_export_preparation import (
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
    try:
        result = asyncio.run(asyncio.wait_for(
            prepare_reference_exports_for_settings(settings), timeout=args.timeout_seconds,
        ))
    except TimeoutError:
        summary: dict = {"status": "timeout"}
    except Exception as exc:  # noqa: BLE001 - 원문(DSN 등)을 출력하지 않는다.
        summary = {"status": "error", "error_type": type(exc).__name__}
    else:
        summary = _summary(result)
    _emit(summary, started)
    return EXIT_OK if summary["status"] in {"success", "not_ready", "disabled"} else EXIT_WARN


if __name__ == "__main__":
    sys.exit(main())
