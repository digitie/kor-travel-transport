"""기준정보 본문 준비의 종류별 격리·오프라인 상한·제한 정리(감사 T23-04·T23-05·T23-12·WLH-04).

DB 없이 준비 루프의 계약을 본다. 실제 PostgreSQL 정리·재사용은 test_reference_prepare_gc.py가 본다.
"""
import asyncio
from datetime import timedelta
from time import monotonic
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy.exc import DBAPIError

from app.dagster.recovery import CollectionLeaseLost
from app.services import export_current, reference_artifacts
from app.services import reference_export_preparation as prep

KINDS = ("bus-terminals-v1", "ferry-ports-v1", "rail-stations-v1", "parking-current-v1")


class FakeSession:
    def __init__(self):
        self.commits = 0
        self.rollbacks = 0
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))
        self.statements = []

    async def commit(self):
        self.commits += 1

    async def rollback(self):
        self.rollbacks += 1

    async def connection(self, **_kwargs):
        return None

    async def execute(self, statement):
        self.statements.append(str(statement))


def _settings():
    return SimpleNamespace(transport_map_current_enabled=True, release_sha="prepare-isolation-test")


def _specs(monkeypatch):
    specs = [SimpleNamespace(kind=kind, max_age=None) for kind in KINDS]
    monkeypatch.setattr(prep, "reference_specs", lambda _settings: specs)
    return specs


def _db_error(sqlstate):
    return DBAPIError("SELECT 1", {}, SimpleNamespace(sqlstate=sqlstate))


def test_one_failing_kind_does_not_stop_the_others(monkeypatch):
    _specs(monkeypatch)
    seen = []

    async def prepare_kind(session, spec, **kwargs):
        seen.append(spec.kind)
        if spec.kind == "ferry-ports-v1":
            raise HTTPException(503, "reference 본문 구성 시간 상한을 초과했습니다.")
        if spec.kind == "parking-current-v1":
            raise _db_error("57014")
        return {"status": "reused" if spec.kind == "rail-stations-v1" else "source_unavailable"}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    session = FakeSession()
    result = asyncio.run(prep.prepare_reference_exports(session, settings=_settings(), collect_garbage=False))
    # 실패 뒤 종류도 계속 준비한다. Map이 읽는 철도역·여객선을 먼저 한다.
    assert seen == ["rail-stations-v1", "ferry-ports-v1", "bus-terminals-v1", "parking-current-v1"]
    assert result["status"] == "partial_success"
    assert (result["prepared"], result["reused"], result["failed"]) == (0, 1, 2)
    by_kind = {row["kind"]: row for row in result["kinds"]}
    assert by_kind["ferry-ports-v1"] == {
        "kind": "ferry-ports-v1", "status": "failed", "error_type": "HTTPException",
        "reason": "reference 본문 구성 시간 상한을 초과했습니다.", "duration_ms": by_kind["ferry-ports-v1"]["duration_ms"],
    }
    assert by_kind["parking-current-v1"]["sqlstate"] == "57014"
    assert by_kind["parking-current-v1"]["error_type"] == "DBAPIError"
    assert all(type(row["duration_ms"]) is int and row["duration_ms"] >= 0 for row in result["kinds"])
    assert session.rollbacks == 2  # 실패한 종류마다 transaction을 비운다.
    assert "gc" not in result


@pytest.mark.parametrize(("statuses", "expected"), [
    (("prepared", "reused", "source_unavailable", "source_unavailable"), "success"),
    (("source_unavailable",) * 4, "not_ready"),
    (("failed", "source_unavailable", "source_unavailable", "unsupported_revision"), "failed"),
    (("failed", "prepared", "failed", "failed"), "partial_success"),
    # 경합(busy)·예산 소진(deferred)은 실패가 아니다: 준비한 종류가 있으면 success, 없으면 deferred.
    (("reused", "busy", "source_unavailable", "deferred"), "success"),
    (("busy", "busy", "source_unavailable", "busy"), "deferred"),
    (("deferred", "source_unavailable", "source_unavailable", "unsupported_revision"), "deferred"),
    (("busy", "failed", "source_unavailable", "source_unavailable"), "partial_success"),
])
def test_overall_status_fails_only_when_nothing_could_be_prepared(monkeypatch, statuses, expected):
    _specs(monkeypatch)
    by_kind = dict(zip(KINDS, statuses, strict=True))

    async def prepare_kind(session, spec, **kwargs):
        if by_kind[spec.kind] == "failed":
            raise RuntimeError("boom")
        return {"status": by_kind[spec.kind]}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    result = asyncio.run(prep.prepare_reference_exports(FakeSession(), settings=_settings(), collect_garbage=False))
    assert result["status"] == expected
    assert (result["busy"], result["deferred"], result["failed"]) == (
        statuses.count("busy"), statuses.count("deferred"), statuses.count("failed"))


@pytest.mark.parametrize("error", [CollectionLeaseLost("revoked"), asyncio.CancelledError()])
def test_lease_loss_and_cancellation_still_stop_the_step(monkeypatch, error):
    _specs(monkeypatch)

    async def prepare_kind(session, spec, **kwargs):
        raise error

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    with pytest.raises(type(error)):
        asyncio.run(prep.prepare_reference_exports(FakeSession(), settings=_settings()))


def test_kinds_filter_prepares_only_the_requested_kind(monkeypatch):
    _specs(monkeypatch)
    seen = []

    async def prepare_kind(session, spec, **kwargs):
        seen.append(spec.kind)
        return {"status": "prepared"}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    result = asyncio.run(prep.prepare_reference_exports(
        FakeSession(), settings=_settings(), kinds=("ferry-ports-v1",), collect_garbage=False,
    ))
    assert seen == ["ferry-ports-v1"] and result["status"] == "success"


def test_offline_preparation_uses_its_own_budget_and_timeouts(monkeypatch):
    """준비는 HTTP 상한(15초·문장 10초·잠금 2초)이 아니라 120초·60초·5초를 쓴다(T23-05)."""
    transactions, budgets = [], []

    async def snapshot_transaction(session, **kwargs):
        transactions.append(kwargs)

    async def heads(session, spec):
        return [SimpleNamespace(last_error=None, confirmed_at=prep.now_utc())]

    async def revision(*_args):
        return "r" * 64

    async def prepare_artifact(session, heads, spec, revision, *, started, budget_seconds):
        budgets.append(started + budget_seconds)
        return SimpleNamespace(id="artifact", item_count=3), True

    monkeypatch.setattr(prep, "_snapshot_transaction", snapshot_transaction)
    monkeypatch.setattr(prep, "_reference_heads", heads)
    monkeypatch.setattr(prep, "_valid_heads", lambda heads, spec: True)
    monkeypatch.setattr(prep, "reference_payload_revision", revision)
    monkeypatch.setattr(prep, "prepare_artifact", prepare_artifact)
    spec = SimpleNamespace(kind="rail-stations-v1", max_age=timedelta(days=6))
    deadline = monotonic() + prep.PREPARE_TOTAL_BUDGET_SECONDS
    result = asyncio.run(prep._prepare_kind(
        FakeSession(), spec, settings=_settings(), deadline=deadline,
        lock_timeout_ms=prep.PREPARE_LOCK_TIMEOUT_MS, statement_timeout_ms=prep.PREPARE_STATEMENT_TIMEOUT_MS,
    ))
    assert result == {"status": "prepared", "artifact_id": "artifact", "item_count": 3, "source_status": "ok"}
    assert transactions == [{"lock_timeout_ms": 5_000, "statement_timeout_ms": 60_000}]
    # 구성 상한의 끝은 전체 예산의 끝(deadline)이다.
    assert budgets == [pytest.approx(deadline)]


def test_snapshot_transaction_keeps_http_literals_and_accepts_offline_values():
    http, offline = FakeSession(), FakeSession()
    asyncio.run(export_current._snapshot_transaction(http))
    asyncio.run(export_current._snapshot_transaction(offline, lock_timeout_ms=5_000, statement_timeout_ms=60_000))
    # 요청 경로는 export 실패 계약(#277)의 문장 그대로다(문장 상한은 남은 요청 예산 이하).
    assert http.statements == ["SET LOCAL lock_timeout = '2s'", "SET LOCAL statement_timeout = 10000"]
    assert offline.statements == ["SET LOCAL lock_timeout = '5s'", "SET LOCAL statement_timeout = '60s'"]
    with pytest.raises(ValueError):
        asyncio.run(export_current._snapshot_transaction(FakeSession(), lock_timeout_ms="1s; SELECT 1"))
    with pytest.raises(ValueError):
        asyncio.run(export_current._snapshot_transaction(FakeSession(), statement_timeout_ms=0))


def test_build_budget_defaults_to_http_and_accepts_the_offline_limit(monkeypatch):
    started = monotonic()
    monkeypatch.setattr(reference_artifacts, "monotonic", lambda: started + 16)
    monkeypatch.setattr(export_current, "monotonic", lambda: started + 16)
    with pytest.raises(HTTPException) as caught:
        reference_artifacts._budget(started)
    assert caught.value.status_code == 503 and caught.value.code == "EXPORT_PREPARE_TIMEOUT"
    reference_artifacts._budget(started, prep.PREPARE_TOTAL_BUDGET_SECONDS)
    with pytest.raises(HTTPException):
        reference_artifacts._budget(started, 15)


def test_bounded_gc_expires_handles_first_then_unused_artifacts(monkeypatch):
    order = []
    handles = [2, 2, 1]
    artifacts = [1, 1]

    async def snapshot_transaction(session, **kwargs):
        # 정리 예산(10초) 안에서 끝나도록 문장 상한도 줄인다.
        assert kwargs["lock_timeout_ms"] == 5_000 and 5_000 <= kwargs["statement_timeout_ms"] <= 10_000

    async def expire(session, *, limit):
        order.append(("handles", limit))
        return handles.pop(0) if handles else 0

    async def unused(session):
        order.append(("artifacts", None))
        return artifacts.pop(0) if artifacts else 0

    monkeypatch.setattr(prep, "_snapshot_transaction", snapshot_transaction)
    monkeypatch.setattr(prep, "expire_snapshots", expire)
    monkeypatch.setattr(prep, "collect_unused_artifact", unused)
    session = FakeSession()
    result = asyncio.run(prep.collect_reference_garbage(session))
    assert (result["expired_handles"], result["unused_artifacts"]) == (5, 2)
    assert [name for name, _ in order] == ["handles"] * 4 + ["artifacts"] * 3
    assert session.commits == 7  # 묶음마다 commit해 잠금을 짧게 쥔다.
    assert "error" not in result


def test_bounded_gc_stops_at_the_victim_cap_and_on_errors(monkeypatch):
    async def snapshot_transaction(session, **kwargs):
        return None

    async def expire(session, *, limit):
        assert 1 <= limit <= 2
        return limit

    async def unused(session):
        raise _db_error("57014")

    monkeypatch.setattr(prep, "_snapshot_transaction", snapshot_transaction)
    monkeypatch.setattr(prep, "expire_snapshots", expire)
    monkeypatch.setattr(prep, "collect_unused_artifact", unused)
    capped = asyncio.run(prep.collect_reference_garbage(FakeSession(), max_victims=5))
    assert capped["expired_handles"] == 5 and capped["unused_artifacts"] == 0

    remaining = [2, 0]

    async def expire_twice(session, *, limit):
        return remaining.pop(0)

    monkeypatch.setattr(prep, "expire_snapshots", expire_twice)
    session = FakeSession()
    failed = asyncio.run(prep.collect_reference_garbage(session))
    assert failed["expired_handles"] == 2 and failed["unused_artifacts"] == 0
    assert failed["error"] == {"error_type": "DBAPIError", "sqlstate": "57014"} and "busy" not in failed
    assert session.rollbacks == 1


def test_preparation_runs_bounded_gc_after_all_kinds(monkeypatch):
    _specs(monkeypatch)
    calls = []

    async def prepare_kind(session, spec, **kwargs):
        calls.append(spec.kind)
        return {"status": "reused"}

    async def gc(session, **kwargs):
        calls.append("gc")
        return {"expired_handles": 1, "unused_artifacts": 1, "duration_ms": 3}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    monkeypatch.setattr(prep, "collect_reference_garbage", gc)
    result = asyncio.run(prep.prepare_reference_exports(FakeSession(), settings=_settings()))
    assert calls == ["rail-stations-v1", "ferry-ports-v1", "bus-terminals-v1", "parking-current-v1", "gc"]
    assert result["gc"]["unused_artifacts"] == 1



def _contended_kind(monkeypatch, errors, deadline_in=120):
    """`_prepare_kind`의 본문 준비(`prepare_artifact`)가 차례로 `errors`를 던지게 한다. None이면 재사용."""
    attempts = []

    async def snapshot_transaction(session, **kwargs):
        return None

    async def heads(session, spec):
        return [SimpleNamespace(last_error=None, confirmed_at=prep.now_utc())]

    async def revision(*_args):
        return "r" * 64

    async def prepare_artifact(session, heads, spec, revision, *, started, budget_seconds):
        error = errors[len(attempts)]
        attempts.append(error)
        if error is not None:
            raise error
        return SimpleNamespace(id="artifact", item_count=3), False

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(prep, "_snapshot_transaction", snapshot_transaction)
    monkeypatch.setattr(prep, "_reference_heads", heads)
    monkeypatch.setattr(prep, "_valid_heads", lambda heads, spec: True)
    monkeypatch.setattr(prep, "reference_payload_revision", revision)
    monkeypatch.setattr(prep, "prepare_artifact", prepare_artifact)
    monkeypatch.setattr(prep.asyncio, "sleep", no_sleep)
    session = FakeSession()
    result = asyncio.run(prep._prepare_kind(
        session, SimpleNamespace(kind="rail-stations-v1", max_age=timedelta(days=6)), settings=_settings(),
        deadline=monotonic() + deadline_in, lock_timeout_ms=5_000, statement_timeout_ms=60_000,
    ))
    return result, attempts, session


@pytest.mark.parametrize("error", [
    export_current.SnapshotRace(), _db_error("55P03"), _db_error("40001"), _db_error("40P01"),
])
def test_contention_retries_once_then_reuses_the_other_builders_body(monkeypatch, error):
    """배포 직후 준비와 5분 공항 수집의 준비가 같은 본문을 두고 겹치면 한 번 다시 보고 대개 재사용한다."""
    result, attempts, session = _contended_kind(monkeypatch, [error, None])
    assert result["status"] == "reused" and len(attempts) == 2
    assert session.rollbacks == 1


@pytest.mark.parametrize(("error", "fields"), [
    (export_current.SnapshotRace(), {"error_type": "SnapshotRace", "reason": "다른 준비·조회와 겹쳤습니다."}),
    (_db_error("55P03"), {"error_type": "DBAPIError", "sqlstate": "55P03"}),
    (_db_error("40001"), {"error_type": "DBAPIError", "sqlstate": "40001"}),
    (_db_error("40P01"), {"error_type": "DBAPIError", "sqlstate": "40P01"}),
])
def test_repeated_contention_is_busy_not_a_failure(monkeypatch, error, fields):
    """두 번째 경합도 예외로 올리지 않는다(예전에는 이 예외가 5분 공항 run step을 실패시켰다)."""
    result, attempts, _session = _contended_kind(monkeypatch, [error, error])
    assert result == {"status": "busy", **fields} and len(attempts) == 2


def test_non_contention_database_errors_are_not_retried(monkeypatch):
    with pytest.raises(DBAPIError):
        _contended_kind(monkeypatch, [_db_error("57014"), None])


def test_busy_kind_keeps_the_run_successful_end_to_end(monkeypatch):
    _specs(monkeypatch)

    async def prepare_kind(session, spec, **kwargs):
        if spec.kind == "rail-stations-v1":
            return {"status": "busy", "error_type": "DBAPIError", "sqlstate": "55P03"}
        return {"status": "reused"}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    result = asyncio.run(prep.prepare_reference_exports(FakeSession(), settings=_settings(), collect_garbage=False))
    assert result["status"] == "success" and (result["busy"], result["failed"]) == (1, 0)
    rail = next(row for row in result["kinds"] if row["kind"] == "rail-stations-v1")
    assert rail["status"] == "busy" and rail["sqlstate"] == "55P03"


def test_gc_contention_stops_quietly(monkeypatch):
    async def snapshot_transaction(session, **kwargs):
        return None

    async def expire(session, *, limit):
        raise _db_error("40001")

    monkeypatch.setattr(prep, "_snapshot_transaction", snapshot_transaction)
    monkeypatch.setattr(prep, "expire_snapshots", expire)
    result = asyncio.run(prep.collect_reference_garbage(FakeSession()))
    assert result["busy"] is True and "error" not in result


def test_contention_without_budget_for_a_retry_is_busy_immediately(monkeypatch):
    """경합 재시도도 전체 예산 안에서만 한다(종류마다 예산을 새로 시작하지 않는다)."""
    result, attempts, _session = _contended_kind(monkeypatch, [_db_error("55P03"), None],
                                                 deadline_in=prep.MIN_KIND_BUDGET_SECONDS + 0.2)
    assert result["status"] == "busy" and len(attempts) == 1


def test_total_budget_is_shared_and_later_kinds_are_deferred_not_cancelled(monkeypatch):
    """예산을 다 쓰면 남은 종류는 시작하지 않고 deferred로 남긴다(step이 metadata 없이 끊기지 않는다)."""
    _specs(monkeypatch)
    clock = {"now": 1_000.0}
    monkeypatch.setattr(prep, "monotonic", lambda: clock["now"])
    seen = []

    async def prepare_kind(session, spec, *, deadline, **kwargs):
        seen.append((spec.kind, round(deadline - clock["now"])))
        clock["now"] += 40  # 종류 하나가 40초 걸린다
        return {"status": "reused"}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    result = asyncio.run(prep.prepare_reference_exports(
        FakeSession(), settings=_settings(), total_budget_seconds=60,
    ))
    # 철도역(남은 60초) → 여객선(남은 20초) → 버스·주차는 남은 예산이 없어 시작하지 않는다.
    assert seen == [("rail-stations-v1", 60), ("ferry-ports-v1", 20)]
    by_kind = {row["kind"]: row for row in result["kinds"]}
    assert by_kind["bus-terminals-v1"]["status"] == by_kind["parking-current-v1"]["status"] == "deferred"
    assert by_kind["bus-terminals-v1"]["reason"] == prep.BUDGET_REASON
    assert result["status"] == "success" and (result["reused"], result["deferred"]) == (2, 2)
    assert result["gc"] == {"expired_handles": 0, "unused_artifacts": 0, "duration_ms": 0, "skipped": "budget"}


@pytest.mark.parametrize("error", [
    HTTPException(503, "reference 본문 구성 시간 상한을 초과했습니다."), _db_error("57014"),
])
def test_timeout_at_the_end_of_the_budget_is_deferred_but_early_timeout_fails(monkeypatch, error):
    _specs(monkeypatch)
    clock = {"now": 1_000.0}
    monkeypatch.setattr(prep, "monotonic", lambda: clock["now"])

    async def prepare_kind(session, spec, *, deadline, **kwargs):
        if spec.kind == "rail-stations-v1":
            clock["now"] = deadline  # 구성이 예산 끝까지 갔다
            raise error
        return {"status": "reused"}

    monkeypatch.setattr(prep, "_prepare_kind", prepare_kind)
    late = asyncio.run(prep.prepare_reference_exports(FakeSession(), settings=_settings(), collect_garbage=False,
                                                      total_budget_seconds=30))
    rail = next(row for row in late["kinds"] if row["kind"] == "rail-stations-v1")
    assert rail["status"] == "deferred" and late["failed"] == 0 and late["status"] == "deferred"

    clock["now"] = 1_000.0

    async def early(session, spec, *, deadline, **kwargs):
        if spec.kind == "rail-stations-v1":
            raise error  # 예산이 넉넉한데 난 상한 초과는 실패다
        return {"status": "reused"}

    monkeypatch.setattr(prep, "_prepare_kind", early)
    result = asyncio.run(prep.prepare_reference_exports(FakeSession(), settings=_settings(), collect_garbage=False))
    rail = next(row for row in result["kinds"] if row["kind"] == "rail-stations-v1")
    assert rail["status"] == "failed" and result["status"] == "partial_success"


def test_attempt_timeouts_never_exceed_the_remaining_budget(monkeypatch):
    monkeypatch.setattr(prep, "monotonic", lambda: 100.0)
    assert prep._attempt_timeouts(130.0, 5_000, 60_000) == (5_000, 30_000)
    assert prep._attempt_timeouts(102.5, 5_000, 60_000) == (2_500, 2_500)
    assert prep._attempt_timeouts(99.0, 5_000, 60_000) == (1_000, 1_000)  # 최소 1초


def test_persistent_busy_is_escalated_to_failed():
    summary = prep._summarize({"kinds": [
        {"kind": "rail-stations-v1", "status": "busy", "sqlstate": "55P03"},
        {"kind": "ferry-ports-v1", "status": "busy", "sqlstate": "55P03"},
        {"kind": "bus-terminals-v1", "status": "reused"},
    ]})
    assert summary["status"] == "success" and summary["busy"] == 2
    prep.escalate_persistent_busy(summary, {"rail-stations-v1"})
    rail = summary["kinds"][0]
    assert rail["status"] == "failed" and "연속 3회" in rail["reason"]
    assert (summary["busy"], summary["failed"], summary["status"]) == (1, 1, "partial_success")
