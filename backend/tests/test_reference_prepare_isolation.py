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
    assert seen == list(KINDS)  # 실패 뒤 종류도 계속 준비한다.
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
    # 경합(busy)은 실패가 아니다: 다른 준비가 같은 본문을 만들고 있다.
    (("busy", "busy", "source_unavailable", "busy"), "success"),
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
    assert (result["busy"], result["failed"]) == (statuses.count("busy"), statuses.count("failed"))


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

    async def prepare_artifact(session, heads, spec, revision, *, budget_seconds):
        budgets.append(budget_seconds)
        return SimpleNamespace(id="artifact", item_count=3), True

    monkeypatch.setattr(prep, "_snapshot_transaction", snapshot_transaction)
    monkeypatch.setattr(prep, "_reference_heads", heads)
    monkeypatch.setattr(prep, "_valid_heads", lambda heads, spec: True)
    monkeypatch.setattr(prep, "reference_payload_revision", revision)
    monkeypatch.setattr(prep, "prepare_artifact", prepare_artifact)
    spec = SimpleNamespace(kind="rail-stations-v1", max_age=timedelta(days=6))
    result = asyncio.run(prep._prepare_kind(
        FakeSession(), spec, settings=_settings(), budget_seconds=prep.PREPARE_BUILD_BUDGET_SECONDS,
        lock_timeout_ms=prep.PREPARE_LOCK_TIMEOUT_MS, statement_timeout_ms=prep.PREPARE_STATEMENT_TIMEOUT_MS,
    ))
    assert result == {"status": "prepared", "artifact_id": "artifact", "item_count": 3, "source_status": "ok"}
    assert transactions == [{"lock_timeout_ms": 5_000, "statement_timeout_ms": 60_000}]
    assert budgets == [120]


def test_snapshot_transaction_keeps_http_literals_and_accepts_offline_values():
    http, offline = FakeSession(), FakeSession()
    asyncio.run(export_current._snapshot_transaction(http))
    asyncio.run(export_current._snapshot_transaction(offline, lock_timeout_ms=5_000, statement_timeout_ms=60_000))
    assert http.statements == ["SET LOCAL lock_timeout = '2s'", "SET LOCAL statement_timeout = '10s'"]
    assert offline.statements == ["SET LOCAL lock_timeout = '5s'", "SET LOCAL statement_timeout = '60s'"]
    with pytest.raises(ValueError):
        asyncio.run(export_current._snapshot_transaction(FakeSession(), lock_timeout_ms="1s; SELECT 1"))
    with pytest.raises(ValueError):
        asyncio.run(export_current._snapshot_transaction(FakeSession(), statement_timeout_ms=0))


def test_build_budget_defaults_to_http_and_accepts_the_offline_limit(monkeypatch):
    started = monotonic()
    monkeypatch.setattr(reference_artifacts, "monotonic", lambda: started + 16)
    with pytest.raises(HTTPException):
        reference_artifacts._budget(started)
    reference_artifacts._budget(started, prep.PREPARE_BUILD_BUDGET_SECONDS)


def test_bounded_gc_expires_handles_first_then_unused_artifacts(monkeypatch):
    order = []
    handles = [2, 2, 1]
    artifacts = [1, 1]

    async def snapshot_transaction(session, **kwargs):
        assert kwargs == {"lock_timeout_ms": 5_000, "statement_timeout_ms": 60_000}

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
    assert calls == [*KINDS, "gc"]
    assert result["gc"]["unused_artifacts"] == 1



def _contended_kind(monkeypatch, errors):
    """`_prepare_kind`의 본문 준비(`prepare_artifact`)가 차례로 `errors`를 던지게 한다. None이면 재사용."""
    attempts = []

    async def snapshot_transaction(session, **kwargs):
        return None

    async def heads(session, spec):
        return [SimpleNamespace(last_error=None, confirmed_at=prep.now_utc())]

    async def revision(*_args):
        return "r" * 64

    async def prepare_artifact(session, heads, spec, revision, *, budget_seconds):
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
        budget_seconds=120, lock_timeout_ms=5_000, statement_timeout_ms=60_000,
    ))
    return result, attempts, session


@pytest.mark.parametrize("error", [
    export_current.SnapshotRace(), _db_error("55P03"), _db_error("40001"),
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
