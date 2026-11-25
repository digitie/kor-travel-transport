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
from app.services import export_references as _export_references
from app.services.export_references import (
    _reference_heads,
    _valid_heads,
    reference_specs,
)
from app.services.reference_artifacts import collect_unused_artifact, prepare_artifact
from app.services.reference_export_revision import reference_payload_revision

logger = logging.getLogger(__name__)

#: 오프라인 준비의 상한. HTTP 첫 페이지(구성 15초·문장 10초·잠금 2초)는 Map 응답 시간을 지키려는 값이다.
#: 준비가 같은 값을 쓰면 CPU가 붐빌 때 HTTP와 같은 이유로 함께 실패한다(T23-05).
#: 시간 예산은 한 번의 준비 **전체**(모든 종류·경합 재시도·정리)에 하나다. 종류마다 새로 시작하지 않고, 남은 예산이
#: 모자라면 그 뒤 종류는 `deferred`로 남긴다(호출자의 run 상한보다 먼저 끝나 step이 metadata 없이 끊기지 않게).
#: - 전용 준비 job·배포 직후·주소 갱신 뒤: 120초(호출자가 run 상한에 맞춰 더 줄인다).
#: - 수집 job 꼬리(5분 공항 수집 등): 60초 — 꼬리가 길면 run이 STARTED로 남아 coalescing schedule이 주차 tick을 버린다.
PREPARE_TOTAL_BUDGET_SECONDS = 120
COLLECTION_TAIL_PREPARE_BUDGET_SECONDS = 60
#: 남은 예산이 이보다 적으면 그 종류를 시작하지 않고 `deferred`로 둔다.
MIN_KIND_BUDGET_SECONDS = 5
PREPARE_STATEMENT_TIMEOUT_MS = 60_000
PREPARE_LOCK_TIMEOUT_MS = 5_000
#: 준비 뒤 정리 상한. 만료 handle을 먼저 지워(그 handle이 붙든 옛 본문을 풀어 준다) 미사용 본문을 정리한다.
#: 요청 경로는 첫 페이지마다 하나씩만 지우므로 준비가 대부분을 맡아 요청 경로의 GC를 드물게 만든다.
GC_MAX_VICTIMS = 50
GC_BUDGET_SECONDS = 10
#: 같은 본문(kind·scope·input revision)을 다른 준비(배포 직후 준비·5분 공항 수집·다른 수집 job)나 첫 HTTP 페이지가
#: 동시에 만들 때의 신호다. 잠금 대기 상한(55P03)·교착(40P01)·RR 직렬화 실패(40001)·admission/head CAS 경합(SnapshotRace).
#: 한 번 새 transaction으로 다시 보고(대개 그사이 끝난 본문을 재사용한다), 그래도 겹치면 실패가 아니라 `busy`다 —
#: 상대가 같은 본문을 만들고 있고, 다음 준비·첫 페이지가 그 본문을 재사용한다. busy는 명시 결과로 남기고(Dagster는
#: deferred), 같은 종류가 연속으로 busy면 호출자가 실패로 올린다(`escalate_persistent_busy`) — 버려진 잠금(idle in
#: transaction) 같은 지속 문제를 성공으로 숨기지 않는다.
CONTENTION_SQLSTATES = frozenset({"40001", "40P01", "55P03"})
CONTENTION_RETRY_DELAY_SECONDS = (0.3, 1.0)
#: Map(kor-travel-map)이 읽는 T3는 철도역·여객선 터미널뿐이다(bus-terminals·parking/current는 소비자 없음).
#: 기동 warmup과 배포 직후 준비의 대상이고, 모든 준비에서 이 순서로 먼저 한다(예산이 모자라면 소비자 없는 종류가 밀린다).
MAP_EXPORT_KINDS = ("rail-stations-v1", "ferry-ports-v1")
STARTUP_WARM_KINDS = MAP_EXPORT_KINDS
STARTUP_WARM_TIMEOUT_SECONDS = 10
#: 종류별 결과 status. 전체 status는 `_summarize`가 정한다.
KIND_STATUSES = ("prepared", "reused", "busy", "deferred", "failed", "source_unavailable", "unsupported_revision")
#: 예산을 다 써서 끝난 종류의 사유(코드 고정 문구).
BUDGET_REASON = "준비 시간 예산을 다 써 다음 준비로 미뤘습니다."
#: 예산 끝 무렵의 시간 상한 오류만 `deferred`로 본다(예산이 넉넉한데 난 상한 초과는 실패다).
_BUDGET_TOLERANCE_SECONDS = 2.0
#: 같은 종류가 이 횟수만큼 연속(이번 포함) busy면 실패로 올린다. 5분 공항 수집이면 약 15분이다.
BUSY_ESCALATION_STREAK = 3


def _code_fingerprint():
    # 모듈 속성으로 읽는다(시험이 지문을 바꿔 끼울 수 있게). RELEASE_SHA는 입력 revision에 들어가지 않는다(ADR-016).
    return _export_references.REFERENCE_PAYLOAD_FINGERPRINT


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
                elif await reference_payload_revision(session, heads, spec.kind, _code_fingerprint()) is None:
                    result["status"] = "unsupported_revision"
                else:
                    result["status"] = "warmed"
        except Exception as exc:  # noqa: BLE001 - 선택적 기동 작업의 실패가 서빙을 방해하지 않는다.
            result.update(status="failed", error_type=type(exc).__name__)
        result["duration_ms"] = _elapsed_ms(started)
        results.append(result)
    return results


async def prepare_reference_exports_for_settings(settings, *, kinds=None,
                                                 total_budget_seconds=PREPARE_TOTAL_BUDGET_SECONDS):
    """동기 주소 갱신 job의 완료 뒤·배포 직후 code-server에서 사용하는 같은 canonical 준비 경로."""
    from app.db.session import create_engine_and_session_factory
    engine, factory = create_engine_and_session_factory(settings.database_url, collector=True)
    try:
        async with factory() as session:
            return await prepare_reference_exports(session, settings=settings, kinds=kinds,
                                                   total_budget_seconds=total_budget_seconds)
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


def _is_budget_exhausted(exc: BaseException, deadline: float) -> bool:
    """본문 구성 상한(503)·statement timeout(57014)이 전체 예산 끝에서 났는가."""
    timed_out = (isinstance(exc, HTTPException) and exc.status_code == 503) or (
        isinstance(exc, DBAPIError) and getattr(exc.orig, "sqlstate", None) == "57014")
    return timed_out and monotonic() >= deadline - _BUDGET_TOLERANCE_SECONDS


async def _rollback_quietly(session) -> None:
    # 끊긴 연결이면 rollback도 실패한다. 다음 종류는 새 transaction에서 다시 판정한다.
    with contextlib.suppress(Exception):
        await session.rollback()


def _attempt_timeouts(deadline: float, lock_timeout_ms: int, statement_timeout_ms: int) -> tuple[int, int]:
    """남은 전체 예산 안에서 끝나도록 문장·잠금 상한을 줄인다(최소 1초)."""
    remaining_ms = max(1_000, int((deadline - monotonic()) * 1000))
    statement = min(statement_timeout_ms, remaining_ms)
    return min(lock_timeout_ms, statement), statement


async def _prepare_kind(session, spec, *, settings, deadline, lock_timeout_ms, statement_timeout_ms):
    for attempt in range(2):
        try:
            attempt_started = monotonic()
            lock_ms, statement_ms = _attempt_timeouts(deadline, lock_timeout_ms, statement_timeout_ms)
            await _snapshot_transaction(session, lock_timeout_ms=lock_ms, statement_timeout_ms=statement_ms)
            heads = await _reference_heads(session, spec)
            if not _valid_heads(heads, spec):
                await session.rollback()
                return {"status": "source_unavailable"}
            revision = await reference_payload_revision(session, heads, spec.kind, _code_fingerprint())
            if revision is None:
                await session.rollback()
                return {"status": "unsupported_revision"}
            source_status = "stale" if any(h.last_error is not None or now_utc() - serialize_utc(h.confirmed_at) > spec.max_age for h in heads) else "ok"
            # 구성 상한도 전체 예산의 끝(deadline)이다. 경합 재시도는 남은 예산만 쓴다(재시도마다 새로 시작하지 않는다).
            artifact, created = await prepare_artifact(
                session, heads, spec, revision, started=attempt_started,
                budget_seconds=max(0.0, deadline - attempt_started),
            )
            result = {"status": "prepared" if created else "reused", "artifact_id": artifact.id,
                      "item_count": artifact.item_count, "source_status": source_status}
            await session.commit()
            return result
        except (SnapshotRace, DBAPIError) as exc:
            await session.rollback()
            if not _is_contention(exc):
                raise
            delay = random.uniform(*CONTENTION_RETRY_DELAY_SECONDS)
            if attempt or deadline - monotonic() - delay < MIN_KIND_BUDGET_SECONDS:
                return {"status": "busy", **_failure_fields(exc)}
            await asyncio.sleep(delay)
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
    deadline = started + budget_seconds
    counts = {"expired_handles": 0, "unused_artifacts": 0}
    error = None
    busy = False

    def remaining():
        return max_victims - counts["expired_handles"] - counts["unused_artifacts"]

    try:
        for key in ("expired_handles", "unused_artifacts"):
            while remaining() > 0 and monotonic() < deadline:
                lock_ms, statement_ms = _attempt_timeouts(deadline, lock_timeout_ms, statement_timeout_ms)
                await _snapshot_transaction(session, lock_timeout_ms=lock_ms, statement_timeout_ms=statement_ms)
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


def _summarize(summary: dict) -> dict:
    """종류별 결과에서 수와 전체 status를 다시 센다.

    - failed가 있으면: 다른 종류가 준비·재사용·경합·이월이면 partial_success, 아니면 failed(공통 원인).
    - 준비·재사용한 종류가 있으면 success(경합·이월 종류는 호출자가 deferred 결과로 따로 남긴다).
    - 경합·이월만 있으면 deferred, 아무것도 없으면(원천 미완결·revision 없음) not_ready.
    """
    rows = summary.get("kinds") or []
    counts = {status: sum(row.get("status") == status for row in rows)
              for status in ("prepared", "reused", "busy", "deferred", "failed")}
    ready = counts["prepared"] + counts["reused"]
    waiting = counts["busy"] + counts["deferred"]
    if counts["failed"]:
        status = "partial_success" if ready + waiting else "failed"
    elif ready:
        status = "success"
    else:
        status = "deferred" if waiting else "not_ready"
    summary.update(counts, status=status)
    return summary


def _ordered_specs(specs):
    # Map이 읽는 종류를 먼저 한다(예산이 모자라면 소비자 없는 종류가 밀린다). 나머지는 기존 순서 그대로.
    rank = {kind: index for index, kind in enumerate(MAP_EXPORT_KINDS)}
    return sorted(specs, key=lambda spec: rank.get(spec.kind, len(rank)))


async def prepare_reference_exports(session, *, settings, kinds=None, collect_garbage=True,
                                    total_budget_seconds=PREPARE_TOTAL_BUDGET_SECONDS,
                                    lock_timeout_ms=PREPARE_LOCK_TIMEOUT_MS,
                                    statement_timeout_ms=PREPARE_STATEMENT_TIMEOUT_MS):
    """종류별로 격리해 본문을 준비하고 결과를 돌려준다.

    예외로 빠져나가는 것은 중단 신호(취소·run 상한)와 회수된 Dagster 실행(`CollectionLeaseLost`)뿐이다.
    나머지는 종류별 status(`KIND_STATUSES`)로 남고 전체 status는 success·partial_success·failed·deferred·not_ready다
    (`_summarize`). 경합(`busy`)·예산 소진(`deferred`)은 실패가 아니다 — 배포 직후 준비와 5분 공항 수집의 준비가
    같은 본문을 두고 겹쳐도 어느 쪽도 실패하지 않는다. 전체 예산(`total_budget_seconds`)은 모든 종류와 정리가 나눠 쓴다.
    """
    if not settings.transport_map_current_enabled:
        return {"status": "disabled", "prepared": 0, "reused": 0, "busy": 0, "deferred": 0, "failed": 0, "kinds": []}
    # API import 경로에서 Dagster 모듈을 미리 읽지 않는다(general_rail_reference와 같은 규칙).
    from app.dagster.recovery import CollectionLeaseLost

    deadline = monotonic() + max(0.0, float(total_budget_seconds))
    results = []
    for spec in _ordered_specs(reference_specs(settings)):
        if kinds is not None and spec.kind not in kinds:
            continue
        started = monotonic()
        if deadline - started < MIN_KIND_BUDGET_SECONDS:
            result = {"status": "deferred", "reason": BUDGET_REASON}
        else:
            try:
                result = await _prepare_kind(session, spec, settings=settings, deadline=deadline,
                                             lock_timeout_ms=lock_timeout_ms, statement_timeout_ms=statement_timeout_ms)
            except CollectionLeaseLost:
                raise
            except Exception as exc:  # noqa: BLE001 - 종류 국소 실패를 격리한다. 중단 신호(BaseException)는 그대로 둔다.
                await _rollback_quietly(session)
                if _is_budget_exhausted(exc, deadline):
                    result = {"status": "deferred", **_failure_fields(exc), "reason": BUDGET_REASON}
                else:
                    result = {"status": "failed", **_failure_fields(exc)}
                    logger.warning(json.dumps({"event": "reference_prepare_failed", "kind": spec.kind, **result},
                                              ensure_ascii=False))
        results.append({"kind": spec.kind, **result, "duration_ms": _elapsed_ms(started)})
    summary = _summarize({"kinds": results})
    if collect_garbage:
        gc_budget = min(GC_BUDGET_SECONDS, deadline - monotonic())
        if gc_budget >= 1:
            summary["gc"] = await collect_reference_garbage(
                session, budget_seconds=gc_budget, lock_timeout_ms=lock_timeout_ms,
                statement_timeout_ms=statement_timeout_ms,
            )
        else:
            summary["gc"] = {"expired_handles": 0, "unused_artifacts": 0, "duration_ms": 0, "skipped": "budget"}
    return summary


def escalate_persistent_busy(summary: dict, persistent_kinds, *, streak: int = BUSY_ESCALATION_STREAK) -> dict:
    """연속 `streak`회 busy인 종류를 failed로 올리고 수·전체 status를 다시 센다.

    정상 경합은 한두 번으로 끝난다(상대 준비가 끝나면 재사용). 계속 겹치면 버려진 잠금(idle in transaction 세션 등)이
    본문 head·admission 행을 쥐고 있을 가능성이 커서 Map 첫 페이지도 2초 잠금 상한으로 503을 받는다.
    """
    persistent = set(persistent_kinds)
    for row in summary.get("kinds") or []:
        if row.get("status") == "busy" and row.get("kind") in persistent:
            row.update(status="failed", reason=f"연속 {streak}회 경합 — 잠금을 쥔 세션(idle in transaction 등)을 확인하세요.")
    return _summarize(summary)
