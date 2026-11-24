"""조회 밖에서 canonical 본문을 준비한다. provider 호출·source head 갱신은 하지 않는다.

준비는 HTTP 첫 페이지의 대체 경로일 뿐이다. 준비가 없거나 실패해도 첫 HTTP 페이지가 같은 입력으로 같은 본문을
직접 만든다(느리지만 정확하다). 그래서 한 종류의 실패는 다른 종류의 준비와 이 단계를 부른 수집 run(5분 공항 수집 등)을
막지 않는다 — 종류별로 격리하고 결과(status·duration_ms·error_type)를 남긴다.
"""
import asyncio
import contextlib
import json
import logging
import random
from time import monotonic

from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.time_utils import now_utc, serialize_utc
from app.services.export_current import (
    SnapshotRace,
    _snapshot_transaction,
    expire_snapshots,
)
from app.services.export_references import (
    _reference_heads,
    _valid_heads,
    reference_specs,
)
from app.services.reference_artifacts import collect_unused_artifact, prepare_artifact
from app.services.reference_export_revision import reference_payload_revision

logger = logging.getLogger(__name__)

#: 오프라인 준비의 상한. HTTP 첫 페이지(구성 15초·문장 10초·잠금 2초)는 Map 응답 시간을 지키려는 값이다.
#: run 상한(180~1800초) 안에서 도는 준비가 같은 값을 쓰면 CPU가 붐빌 때 HTTP와 같은 이유로 함께 실패한다(T23-05).
PREPARE_BUILD_BUDGET_SECONDS = 120
PREPARE_STATEMENT_TIMEOUT_MS = 60_000
PREPARE_LOCK_TIMEOUT_MS = 5_000
#: 준비 뒤 정리 상한. 만료 handle을 먼저 지워(그 handle이 붙든 옛 본문을 풀어 준다) 미사용 본문을 정리한다.
#: 요청 경로는 첫 페이지마다 하나씩만 지우므로 준비가 대부분을 맡아 요청 경로의 GC를 드물게 만든다.
GC_MAX_VICTIMS = 50
GC_BUDGET_SECONDS = 10
#: 같은 본문(kind·scope·input revision)을 다른 준비(배포 직후 준비·5분 공항 수집·다른 수집 job)나 첫 HTTP 페이지가
#: 동시에 만들 때의 신호다. 잠금 대기 상한(55P03)·RR 직렬화 실패(40001)·admission/head CAS 경합(SnapshotRace).
#: 한 번 새 transaction으로 다시 보고(대개 그사이 끝난 본문을 재사용한다), 그래도 겹치면 실패가 아니라 `busy`다 —
#: 상대가 같은 본문을 만들고 있고, 다음 준비·첫 페이지가 그 본문을 재사용한다.
CONTENTION_SQLSTATES = frozenset({"40001", "55P03"})
CONTENTION_RETRY_DELAY_SECONDS = (0.3, 1.0)
#: 기동 warmup 대상. Map(kor-travel-map)이 읽는 T3는 철도역·여객선 터미널뿐이다(bus-terminals·parking/current는 소비자 없음).
STARTUP_WARM_KINDS = ("rail-stations-v1", "ferry-ports-v1")
STARTUP_WARM_TIMEOUT_SECONDS = 10


def _elapsed_ms(started: float) -> int:
    return round((monotonic() - started) * 1000)


async def warm_reference_revisions(session_factory, *, settings, kinds=STARTUP_WARM_KINDS,
                                   timeout_seconds=STARTUP_WARM_TIMEOUT_SECONDS):
    """HTTP 요청과 같은 워커의 입력 지문 memo를 종류별로 하나씩 채운다.

    읽기 전용이고 본문은 만들지 않는다. 종류별 상한 안에서 실패는 결과로만 남기고 다음 종류로 넘어간다.
    """
    specs = {spec.kind: spec for spec in reference_specs(settings)}
    results = []
    for kind in kinds:
        started = monotonic()
        result = {"kind": kind}
        try:
            spec = specs[kind]
            async with asyncio.timeout(timeout_seconds), session_factory() as session:
                await _snapshot_transaction(session)
                await session.execute(text("SET TRANSACTION READ ONLY"))
                heads = await _reference_heads(session, spec)
                if not _valid_heads(heads, spec):
                    result["status"] = "source_unavailable"
                elif await reference_payload_revision(session, heads, spec.kind, settings.release_sha) is None:
                    result["status"] = "unsupported_revision"
                else:
                    result["status"] = "warmed"
        except Exception as exc:  # noqa: BLE001 - 선택적 기동 작업의 실패가 서빙을 방해하지 않는다.
            result.update(status="failed", error_type=type(exc).__name__)
        result["duration_ms"] = _elapsed_ms(started)
        results.append(result)
    return results


async def prepare_reference_exports_for_settings(settings, *, kinds=None):
    """동기 주소 갱신 job의 완료 뒤·배포 직후 code-server에서 사용하는 같은 canonical 준비 경로."""
    from app.db.session import create_engine_and_session_factory
    engine, factory = create_engine_and_session_factory(settings.database_url, collector=True)
    try:
        async with factory() as session:
            return await prepare_reference_exports(session, settings=settings, kinds=kinds)
    finally:
        await engine.dispose()


def _failure_fields(exc: BaseException) -> dict:
    """공용 Dagster event log에 남겨도 되는 값만: 예외 종류, SQLSTATE, 코드에 고정한 사유 문구."""
    fields = {"error_type": type(exc).__name__}
    if isinstance(exc, DBAPIError):
        code = getattr(exc.orig, "sqlstate", None)
        if isinstance(code, str) and len(code) == 5:
            fields["sqlstate"] = code
    elif isinstance(exc, SnapshotRace):
        fields["reason"] = "다른 준비·조회와 겹쳤습니다."
    elif isinstance(exc, HTTPException) and isinstance(exc.detail, str):
        # 이 경로의 503 사유는 코드의 고정 문구다(원천 값·DSN을 담지 않는다). 시간 상한·크기 상한·membership을 가른다.
        fields["reason"] = exc.detail[:200]
    return fields


def _is_contention(exc: BaseException) -> bool:
    if isinstance(exc, SnapshotRace):
        return True
    return isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) in CONTENTION_SQLSTATES


async def _rollback_quietly(session) -> None:
    # 끊긴 연결이면 rollback도 실패한다. 다음 종류는 새 transaction에서 다시 판정한다.
    with contextlib.suppress(Exception):
        await session.rollback()


async def _prepare_kind(session, spec, *, settings, budget_seconds, lock_timeout_ms, statement_timeout_ms):
    for attempt in range(2):
        try:
            await _snapshot_transaction(
                session, lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms,
            )
            heads = await _reference_heads(session, spec)
            if not _valid_heads(heads, spec):
                await session.rollback()
                return {"status": "source_unavailable"}
            revision = await reference_payload_revision(session, heads, spec.kind, settings.release_sha)
            if revision is None:
                await session.rollback()
                return {"status": "unsupported_revision"}
            source_status = "stale" if any(h.last_error is not None or now_utc() - serialize_utc(h.confirmed_at) > spec.max_age for h in heads) else "ok"
            artifact, created = await prepare_artifact(session, heads, spec, revision, budget_seconds=budget_seconds)
            result = {"status": "prepared" if created else "reused", "artifact_id": artifact.id,
                      "item_count": artifact.item_count, "source_status": source_status}
            await session.commit()
            return result
        except (SnapshotRace, DBAPIError) as exc:
            await session.rollback()
            if not _is_contention(exc):
                raise
            if attempt:
                return {"status": "busy", **_failure_fields(exc)}
            await asyncio.sleep(random.uniform(*CONTENTION_RETRY_DELAY_SECONDS))
        except BaseException:
            await session.rollback()
            raise
    raise AssertionError("unreachable")  # pragma: no cover


async def collect_reference_garbage(session, *, max_victims=GC_MAX_VICTIMS, budget_seconds=GC_BUDGET_SECONDS,
                                    lock_timeout_ms=PREPARE_LOCK_TIMEOUT_MS,
                                    statement_timeout_ms=PREPARE_STATEMENT_TIMEOUT_MS):
    """만료 handle → 미사용 본문 순으로 상한(개수·시간)까지 정리한다. 묶음마다 commit해 잠금을 짧게 쥔다.

    정리 실패는 준비 결과를 바꾸지 않는다(다음 준비·첫 페이지가 이어서 정리한다).
    """
    started = monotonic()
    counts = {"expired_handles": 0, "unused_artifacts": 0}
    error = None
    busy = False

    def remaining():
        return max_victims - counts["expired_handles"] - counts["unused_artifacts"]

    try:
        for key in ("expired_handles", "unused_artifacts"):
            while remaining() > 0 and monotonic() - started < budget_seconds:
                await _snapshot_transaction(
                    session, lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms,
                )
                if key == "expired_handles":
                    deleted = await expire_snapshots(session, limit=min(2, remaining()))
                else:
                    deleted = await collect_unused_artifact(session)
                await session.commit()
                if not deleted:
                    break
                counts[key] += deleted
    except Exception as exc:  # noqa: BLE001 - 정리는 부가 작업이다.
        await _rollback_quietly(session)
        if _is_contention(exc):
            # 다른 정리·준비가 같은 victim을 다루는 중이다. 남은 것은 다음 준비가 이어서 지운다.
            busy = True
        else:
            error = _failure_fields(exc)
    result = {**counts, "duration_ms": _elapsed_ms(started)}
    if busy:
        result["busy"] = True
    if error:
        result["error"] = error
    return result


def _overall_status(prepared: int, reused: int, busy: int, failed: int) -> str:
    # busy는 다른 준비가 같은 본문을 만드는 중이라는 뜻이라 성공 쪽에 센다(경합으로 수집 run을 실패·부분으로 만들지 않는다).
    ready = prepared + reused + busy
    if failed:
        # 한 종류라도 준비·재사용했으면 종류 국소 실패다(다음 실행이 다시 한다). 모두 실패면 공통 원인이다.
        return "partial_success" if ready else "failed"
    return "success" if ready else "not_ready"


async def prepare_reference_exports(session, *, settings, kinds=None, collect_garbage=True,
                                    budget_seconds=PREPARE_BUILD_BUDGET_SECONDS,
                                    lock_timeout_ms=PREPARE_LOCK_TIMEOUT_MS,
                                    statement_timeout_ms=PREPARE_STATEMENT_TIMEOUT_MS):
    """종류별로 격리해 본문을 준비하고 결과를 돌려준다.

    예외로 빠져나가는 것은 중단 신호(취소·run 상한)와 회수된 Dagster 실행(`CollectionLeaseLost`)뿐이다.
    나머지 실패는 `kinds[*].status == "failed"`로 남기고, 전체 `status`는 success·partial_success·failed·not_ready다.
    경합(`busy`)은 실패가 아니다 — 배포 직후 준비와 5분 공항 수집의 준비가 같은 본문을 두고 겹쳐도 어느 쪽도 실패하지 않는다.
    """
    if not settings.transport_map_current_enabled:
        return {"status": "disabled", "prepared": 0, "reused": 0, "busy": 0, "failed": 0, "kinds": []}
    # API import 경로에서 Dagster 모듈을 미리 읽지 않는다(general_rail_reference와 같은 규칙).
    from app.dagster.recovery import CollectionLeaseLost

    results = []
    for spec in reference_specs(settings):
        if kinds is not None and spec.kind not in kinds:
            continue
        started = monotonic()
        try:
            result = await _prepare_kind(session, spec, settings=settings, budget_seconds=budget_seconds,
                                         lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms)
        except CollectionLeaseLost:
            raise
        except Exception as exc:  # noqa: BLE001 - 종류 국소 실패를 격리한다. 중단 신호(BaseException)는 그대로 둔다.
            await _rollback_quietly(session)
            result = {"status": "failed", **_failure_fields(exc)}
            logger.warning(json.dumps({"event": "reference_prepare_failed", "kind": spec.kind, **result},
                                      ensure_ascii=False))
        results.append({"kind": spec.kind, **result, "duration_ms": _elapsed_ms(started)})
    prepared = sum(r["status"] == "prepared" for r in results)
    reused = sum(r["status"] == "reused" for r in results)
    busy = sum(r["status"] == "busy" for r in results)
    failed = sum(r["status"] == "failed" for r in results)
    summary = {"status": _overall_status(prepared, reused, busy, failed), "prepared": prepared, "reused": reused,
               "busy": busy, "failed": failed, "kinds": results}
    if collect_garbage:
        summary["gc"] = await collect_reference_garbage(
            session, lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms,
        )
    return summary

