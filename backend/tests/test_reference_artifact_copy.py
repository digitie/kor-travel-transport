"""실제 asyncpg COPY의 묶음·원자성·취소·요청 계측 계약."""

# ruff: noqa: F811
import asyncio
import hashlib
import json
from time import monotonic
from uuid import uuid4

import asyncpg
import pytest
from app.core import read_timing
from app.core.time_utils import now_utc
from app.models import ReferenceExportArtifact as Artifact
from app.models import ReferenceExportArtifactItem as Item
from app.services import export_current
from app.services import reference_artifacts as artifacts
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import DBAPIError
from test_service_exports import _run, export_client  # noqa: F401


def _encoded(count=402):
    return [
        json.dumps(
            {
                "n": i,
                "한글": "익산 / ' 001\n\t",
                "price": 2000.35,
                "zero": -0.0,
                "missing": None,
            },
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
        for i in range(count)
    ]


async def _store(session, identity, bodies):
    session.add(
        Artifact(
            id=identity,
            kind="copy-test",
            scope_key="test",
            input_revision=identity,
            created_at=now_utc(),
            source_collected_at=now_utc(),
            item_count=len(bodies),
            byte_count=sum(map(len, bodies)),
            content_digest=hashlib.sha256(b"\n".join(bodies) + b"\n").hexdigest(),
        )
    )
    await session.flush()
    await artifacts._store_items(session, identity, bodies, monotonic())


def _require_copy(client):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("실제 PostgreSQL/asyncpg COPY 계약")
    assert client.app.state.engine.dialect.driver == "asyncpg"


def test_native_copy_preserves_bounded_rows_same_transaction_and_timing(
    export_client, monkeypatch
):
    c = export_client
    _require_copy(c)
    original = asyncpg.Connection.copy_records_to_table
    calls = []
    bodies = _encoded()
    identity = str(uuid4())

    async def track(connection, table, **kwargs):
        records = kwargs["records"]
        assert connection.is_in_transaction()
        assert table == Item.__tablename__
        assert kwargs["columns"] == ("artifact_id", "ordinal", "payload")
        assert all(isinstance(row[2], str) for row in records)
        calls.append((len(records), records[0][1], records[-1][1]))
        return await original(connection, table, **kwargs)

    monkeypatch.setattr(asyncpg.Connection, "copy_records_to_table", track)

    async def check(session):
        timing = read_timing.ReadTiming()
        token = read_timing._current.set(timing)
        try:
            await _store(session, identity, bodies)
        finally:
            read_timing._current.reset(token)
        assert timing.statements == 3  # artifact INSERT 1 + native COPY 2
        assert timing.sql_seconds > 0
        rows = (
            await session.execute(
                select(Item.ordinal, Item.payload)
                .where(Item.artifact_id == identity)
                .order_by(Item.ordinal)
            )
        ).all()
        assert [r.ordinal for r in rows] == list(range(1, 403))
        assert [r.payload for r in rows] == [json.loads(body) for body in bodies]

    _run(c, check)
    assert calls == [(400, 1, 400), (2, 401, 402)]


@pytest.mark.parametrize("failure", ["exception", "cancel", "wrong_count", "duplicate"])
def test_second_copy_failure_never_commits_partial_artifact(
    export_client, monkeypatch, failure
):
    c = export_client
    _require_copy(c)
    original = asyncpg.Connection.copy_records_to_table
    calls = 0
    identity = str(uuid4())
    bodies = _encoded()

    async def fail(connection, table, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 2:
            if failure == "exception":
                raise RuntimeError("synthetic COPY failure")
            if failure == "cancel":
                raise asyncio.CancelledError()
            if failure == "duplicate":
                kwargs["records"] = [(identity, 1, bodies[0].decode())]
            result = await original(connection, table, **kwargs)
            return "COPY 0" if failure == "wrong_count" else result
        return await original(connection, table, **kwargs)

    monkeypatch.setattr(asyncpg.Connection, "copy_records_to_table", fail)

    async def attempt(session):
        await _store(session, identity, bodies)

    expected = {
        "exception": RuntimeError,
        "cancel": asyncio.CancelledError,
        "wrong_count": HTTPException,
        "duplicate": DBAPIError,
    }[failure]
    with pytest.raises(expected):
        _run(c, attempt)
    assert calls == 2

    async def verify(session):
        assert (
            await session.scalar(
                select(func.count())
                .select_from(Item)
                .where(Item.artifact_id == identity)
            )
            == 0
        )
        assert await session.get(Artifact, identity) is None

    _run(c, verify)


def test_copy_budget_is_checked_after_each_batch(export_client, monkeypatch):
    c = export_client
    _require_copy(c)
    original = asyncpg.Connection.copy_records_to_table
    calls = 0
    identity = str(uuid4())

    async def advance(connection, table, **kwargs):
        nonlocal calls
        result = await original(connection, table, **kwargs)
        calls += 1
        # 예산 판정은 export_current의 공유 helper(`budget_exceeded`)가 한다.
        monkeypatch.setattr(export_current, "monotonic", lambda: started + 16)
        return result

    monkeypatch.setattr(asyncpg.Connection, "copy_records_to_table", advance)
    started = monotonic()

    async def attempt(session):
        await _store(session, identity, _encoded())

    with pytest.raises(HTTPException, match="") as error:
        _run(c, attempt)
    assert error.value.status_code == 503 and calls == 1

    async def verify(session):
        assert await session.get(Artifact, identity) is None

    _run(c, verify)


def test_native_statement_counts_failure_and_restores_context():
    timing = read_timing.ReadTiming()
    token = read_timing._current.set(timing)
    try:
        with pytest.raises(RuntimeError), read_timing.observe_native_statement():
            raise RuntimeError("failure")
        assert timing.statements == 1 and timing.sql_seconds == 0
        with read_timing.observe_native_statement():
            pass
        assert timing.statements == 2 and timing.sql_seconds >= 0
    finally:
        read_timing._current.reset(token)
    assert read_timing._current.get() is None


@pytest.mark.parametrize(
    "exception,failures,status,attempts",
    [
        (asyncpg.SerializationError, 1, 200, 2),
        # 2026-11-24(감사 T23-01): 55P03은 예전의 즉시 503 대신 공유 예산 안에서 새 RR로 한 번 더 시도한다.
        (asyncpg.LockNotAvailableError, 1, 200, 2),
        (asyncpg.LockNotAvailableError, 2, 503, 2),
    ],
)
def test_native_copy_keeps_existing_reader_retry_policy(
    export_client, monkeypatch, exception, failures, status, attempts
):
    from app.services import export_current
    from test_reference_export_reuse import _get, _prepare

    c = export_client
    _require_copy(c)
    _prepare(c)
    monkeypatch.setattr(export_current, "LOCK_RETRY_DELAY_SECONDS", (0.0, 0.0))
    original = asyncpg.Connection.copy_records_to_table
    calls = 0

    async def fail_first(connection, table, **kwargs):
        nonlocal calls
        calls += 1
        if calls <= failures:
            raise exception("synthetic SQLSTATE")
        return await original(connection, table, **kwargs)

    monkeypatch.setattr(asyncpg.Connection, "copy_records_to_table", fail_first)
    response = _get(c)
    assert response.status_code == status, response.text
    assert calls == attempts
    if status == 200:
        assert response.json()["items"] and response.headers["ETag"]
    else:
        assert response.json()["code"] == "EXPORT_BUSY" and response.headers["retry-after"] == "10"

        async def verify(session):
            assert await session.scalar(select(func.count()).select_from(Artifact)) == 0
            assert await session.scalar(select(func.count()).select_from(Item)) == 0

        _run(c, verify)


@pytest.mark.parametrize(
    "error,status",
    [
        # SQLSTATE 없는 driver 연결 오류는 연결 무효로 표시돼 export 경로에서 503 TRANSIENT_DB다.
        (lambda: asyncpg.InterfaceError("cannot perform operation: connection is closed"), 503),
        (lambda: ConnectionResetError(104, "Connection reset by peer"), 503),
        # 끊긴 연결의 SQLSTATE 08003도 같다.
        (lambda: asyncpg.ConnectionDoesNotExistError("connection was closed in the middle of operation"), 503),
        # 그 밖의 InterfaceError는 프로그램 오류라 예전처럼 500이다.
        (lambda: asyncpg.InterfaceError("cannot perform operation: another operation is in progress"), 500),
    ],
)
def test_native_copy_connection_errors_are_classified(export_client, monkeypatch, error, status):
    from fastapi.testclient import TestClient
    from test_reference_export_reuse import HEADERS, PATH, _prepare
    from test_service_exports import LOOPBACK_CLIENT

    c = export_client
    _require_copy(c)
    _prepare(c)

    async def broken(connection, table, **kwargs):
        raise error()

    monkeypatch.setattr(asyncpg.Connection, "copy_records_to_table", broken)
    lenient = TestClient(c.app, client=LOOPBACK_CLIENT, raise_server_exceptions=False)
    response = lenient.get(PATH, headers=HEADERS, params={"limit": 1})
    assert response.status_code == status, response.text
    if status == 503:
        assert response.json()["code"] == "TRANSIENT_DB" and response.headers["retry-after"] == "15"
