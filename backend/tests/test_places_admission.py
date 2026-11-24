"""장소 지도 입장 제한·대기 중 동일 요청 합치기·전체 시한·연결 끊김·연결 반납 순서(감사 MUI-02·04) 회귀 검사."""

import asyncio
from types import SimpleNamespace

import httpx
import pytest
from anyio import CapacityLimiter
from fastapi import HTTPException
from sqlalchemy import text
from starlette.responses import Response

from app.main import create_app
from app.services.fuel_station_filters import FuelStationFilters
from app.services.place_map_admission import (
    BUSY_RETRY_AFTER_SECONDS,
    CLIENT_CLOSED_STATUS,
    TIMEOUT_RETRY_AFTER_SECONDS,
    PlaceMapGate,
    place_map_admission,
    request_key,
)

PLACES = "/v1/transport/features/places"


async def settle(rounds: int = 10) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def wait_until(condition, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


def busy(exc: BaseException) -> bool:
    return (isinstance(exc, HTTPException) and exc.status_code == 429
            and exc.headers == {"Retry-After": str(BUSY_RETRY_AFTER_SECONDS)})


def timed_out(exc: BaseException) -> bool:
    return (isinstance(exc, HTTPException) and exc.status_code == 504
            and exc.headers == {"Retry-After": str(TIMEOUT_RETRY_AFTER_SECONDS)})


def receiver(gone: asyncio.Event):
    """GET 본문 한 번 뒤 `gone`이 켜지면 http.disconnect를 주는 ASGI receive."""
    first = True

    async def receive():
        nonlocal first
        if first:
            first = False
            return {"type": "http.request", "body": b"", "more_body": False}
        await gone.wait()
        return {"type": "http.disconnect"}

    return receive


def fake_request(gate, gone):
    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(place_map_gate=gate)), receive=receiver(gone))


def page_builds(response) -> int:
    return int(response.headers["server-timing"].split('page_builds;desc="')[1].split('"')[0])


def test_full_queue_rejects_immediately_without_starting_work():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=1)
        release = asyncio.Event()
        started = []

        async def compute(name):
            started.append(name)
            await release.wait()
            return Response(content=name.encode())

        first = asyncio.create_task(gate.run(("a",), lambda: compute("a")))
        await settle()
        queued = asyncio.create_task(gate.run(("b",), lambda: compute("b")))
        await settle()
        assert gate.running == 1 and gate.waiting == 1
        with pytest.raises(HTTPException) as rejected:
            await gate.run(("c",), lambda: compute("c"))
        assert busy(rejected.value)
        assert started == ["a"] and gate.stats["rejected"] == 1
        release.set()
        assert (await first).body == b"a" and (await queued).body == b"b"
        assert started == ["a", "b"]
        assert gate.running == gate.waiting == 0 and not gate.pending

    asyncio.run(exercise())


def test_identical_waiting_requests_share_one_read_but_never_join_a_started_read():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=2)
        release = asyncio.Event()
        calls = {"x": 0, "y": 0}

        async def compute(name):
            calls[name] += 1
            number = calls[name]
            await release.wait()
            return Response(content=f"{name}{number}".encode(), media_type="application/json")

        running = asyncio.create_task(gate.run(("x",), lambda: compute("x")))
        await settle()
        # 같은 키가 이미 DB 읽기를 시작했다. 새 요청은 그 결과(저장 전 snapshot일 수 있다)를 받지 않는다.
        later_same = asyncio.create_task(gate.run(("x",), lambda: compute("x")))
        await settle()
        leader = asyncio.create_task(gate.run(("y",), lambda: compute("y")))
        await settle()
        followers = [asyncio.create_task(gate.run(("y",), lambda: compute("y"))) for _ in range(5)]
        await settle()
        assert gate.waiting == 2 and set(gate.pending) == {("x",), ("y",)}
        assert gate.stats["coalesced"] == 5 and gate.stats["rejected"] == 0
        release.set()
        results = await asyncio.gather(running, later_same, leader, *followers)
        assert [result.body for result in results[:2]] == [b"x1", b"x2"]
        assert {result.body for result in results[2:]} == {b"y1"} and calls == {"x": 2, "y": 1}
        # 합류한 요청마다 별도 Response다. FastAPI가 반환 객체에 요청별 background를 붙인다.
        assert len({id(result) for result in results[2:]}) == 6
        assert all(result.headers["content-type"] == "application/json" for result in results[2:])
        assert gate.running == gate.waiting == 0 and not gate.pending

    asyncio.run(exercise())


def test_deadline_cancels_work_rolls_back_frees_the_slot_and_fails_followers():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=2, deadline_seconds=0.05)
        stopped = asyncio.Event()
        rollbacks = []

        async def stuck():
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def rollback():
            rollbacks.append(True)

        holder = asyncio.create_task(gate.run(("holder",), stuck, on_timeout=rollback))
        await settle()
        queued = asyncio.create_task(gate.run(("queued",), stuck))
        await settle()
        follower = asyncio.create_task(gate.run(("queued",), stuck))
        results = await asyncio.wait_for(asyncio.gather(holder, queued, follower, return_exceptions=True), 2)
        assert all(timed_out(result) for result in results), results
        assert stopped.is_set() and rollbacks == [True]
        assert gate.running == gate.waiting == 0 and not gate.pending and gate.stats["timed_out"] >= 2

        async def ok():
            return Response(content=b"ok")

        assert (await gate.run(("holder",), ok)).body == b"ok"

    asyncio.run(exercise())


def test_cancelled_waiting_leader_gives_identical_followers_a_fresh_read():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=2)
        release = asyncio.Event()
        calls = 0

        async def compute():
            nonlocal calls
            calls += 1
            await release.wait()
            return Response(content=b"done")

        holder = asyncio.create_task(gate.run(("holder",), compute))
        await settle()
        leader = asyncio.create_task(gate.run(("k",), compute))
        await settle()
        follower = asyncio.create_task(gate.run(("k",), compute))
        await settle()
        leader.cancel()
        with pytest.raises(asyncio.CancelledError):
            await leader
        await settle()
        # 합류했던 요청이 새 리더로 다시 줄을 선다.
        assert ("k",) in gate.pending and gate.waiting == 1
        release.set()
        assert (await follower).body == b"done" and (await holder).body == b"done"
        assert calls == 2 and not gate.pending and gate.running == gate.waiting == 0

    asyncio.run(exercise())


def test_leader_error_reaches_followers():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=1)
        release = asyncio.Event()

        async def hold():
            await release.wait()
            return Response(content=b"")

        async def invalid():
            raise HTTPException(status_code=422, detail="필터 선택 개수와 값을 확인해 주세요.")

        holder = asyncio.create_task(gate.run(("holder",), hold))
        await settle()
        leader = asyncio.create_task(gate.run(("bad",), invalid))
        follower = asyncio.create_task(gate.run(("bad",), invalid))
        await settle()
        release.set()
        results = await asyncio.gather(leader, follower, holder, return_exceptions=True)
        assert [getattr(result, "status_code", None) for result in results[:2]] == [422, 422]
        assert gate.stats["coalesced"] == 1 and not gate.pending

    asyncio.run(exercise())


def test_request_key_uses_parsed_query_values_only():
    first = request_key({"request": object(), "session": object(), "limit": 300, "kinds": "rail_station",
                         "station_filters": FuelStationFilters(brands=("SKE",))})
    same = request_key({"station_filters": FuelStationFilters(brands=("SKE",)), "kinds": "rail_station",
                        "limit": 300, "session": object(), "request": object()})
    assert first == same and hash(first) == hash(same)
    assert first != request_key({"limit": 301, "kinds": "rail_station",
                                 "station_filters": FuelStationFilters(brands=("SKE",))})
    assert request_key({"limit": 300, "unhashable": []}) is None


def test_places_route_maps_deadline_to_problem_504_with_retry_after(client):
    client.app.state.place_map_gate = PlaceMapGate(deadline_seconds=1e-9)
    response = client.get(f"{PLACES}?kinds=rail_station,airport&limit=5")
    assert response.status_code == 504, response.text
    assert response.headers["retry-after"] == str(TIMEOUT_RETRY_AFTER_SECONDS)
    assert response.headers["content-type"].startswith("application/problem+json")
    assert response.json()["status"] == 504 and response.json()["instance"] == PLACES
    client.app.state.place_map_gate = PlaceMapGate()
    assert client.get(f"{PLACES}?kinds=rail_station,airport&limit=5").status_code == 200


def test_places_route_coalesces_identical_waiting_requests_and_rejects_overflow(test_settings):
    async def exercise():
        app = create_app(test_settings)
        async with app.router.lifespan_context(app):
            gate = app.state.place_map_gate = PlaceMapGate(max_running=1, max_waiting=1)
            release = asyncio.Event()

            async def other_reader():
                await release.wait()
                return Response(content=b"{}")

            holder = asyncio.create_task(gate.run(("other",), other_reader))
            await settle()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                path = f"{PLACES}?kinds=rail_station,airport&limit=20"
                same = [asyncio.create_task(http.get(path)) for _ in range(3)]
                await wait_until(lambda: gate.stats["coalesced"] == 2)
                rejected = await http.get(f"{path}&include_sources=false")
                assert rejected.status_code == 429 and rejected.headers["retry-after"] == str(BUSY_RETRY_AFTER_SECONDS)
                assert rejected.headers["content-type"].startswith("application/problem+json")
                release.set()
                responses = await asyncio.gather(*same)
            await holder
        assert [response.status_code for response in responses] == [200, 200, 200]
        # 리더 한 번만 장소 본문을 만들고 합류한 요청은 같은 바이트를 받는다.
        assert len({response.content for response in responses}) == 1
        assert sorted(page_builds(response) for response in responses) == [0, 0, 1]
        assert not gate.pending and gate.running == gate.waiting == 0

    asyncio.run(exercise())


def test_places_session_has_local_statement_limit_and_deadline_cancels_real_query(test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL 문장 상한·취소 검증")
    from app.db.session import create_engine_and_session_factory

    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        seen = {}

        async def handler(*, request, session, limit):
            seen["inside"] = await session.scalar(text("SHOW statement_timeout"))
            await session.execute(text("SELECT pg_sleep(5)"))

        wrapped = place_map_admission(handler)
        request = fake_request(PlaceMapGate(deadline_seconds=0.3), asyncio.Event())
        try:
            async with factory() as session:
                loop = asyncio.get_running_loop()
                started = loop.time()
                with pytest.raises(HTTPException) as failure:
                    await wrapped(request=request, session=session, limit=1)
                assert timed_out(failure.value) and loop.time() - started < 3
                assert seen["inside"] == "25s"
                # rollback 뒤 같은 session의 새 transaction에도 상한이 붙고 연결은 계속 쓸 수 있다.
                assert await session.scalar(text("SHOW statement_timeout")) == "25s"
            async with factory() as other:
                # SET LOCAL이라 다른 요청(같은 엔진)의 기본 상한(120초)은 바뀌지 않는다.
                # PostgreSQL은 120s를 큰 단위(2min)로 보여 준다.
                assert await other.scalar(text("SHOW statement_timeout")) in ("2min", "120s")
        finally:
            await engine.dispose()

    asyncio.run(exercise())


def test_fuel_detail_waits_for_validation_limiter_without_holding_a_connection(test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("PostgreSQL 연결 상태 검증")
    from test_place_map_validation import _seed_places_and_prices

    async def exercise():
        app = create_app(test_settings)
        async with app.router.lifespan_context(app):
            async with app.state.session_factory() as session:
                await _seed_places_and_prices(session)
                await session.commit()
            limiter = app.state.fuel_map_limiter = CapacityLimiter(1)
            await limiter.acquire()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                pending = asyncio.create_task(http.get(f"{PLACES}?kind=fuel_station&limit=10"))
                try:
                    await wait_until(lambda: limiter.statistics().tasks_waiting == 1)
                    async with app.state.engine.connect() as probe:
                        held = await probe.scalar(text(
                            "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                            "AND pid <> pg_backend_pid() AND state LIKE 'idle in transaction%'"))
                    # 모든 SQL을 끝내고 연결을 반납한 뒤 검증 slot을 기다린다.
                    assert held == 0
                finally:
                    limiter.release()
                response = await pending
        assert response.status_code == 200, response.text
        body = response.json()
        # 시드 3곳 중 1곳은 위도가 없어 지도 범위 밖이다.
        assert body["kind_totals"] == {"fuel_station": 2} and len(body["items"]) == 2

    asyncio.run(exercise())


def test_client_disconnect_cancels_unshared_work_and_rolls_back():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=1)
        gone = asyncio.Event()
        entered, stopped = asyncio.Event(), asyncio.Event()
        rollbacks = []

        async def handler(*, request, session, limit):
            entered.set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped.set()

        async def rollback():
            rollbacks.append(True)

        session = SimpleNamespace(rollback=rollback, get_bind=lambda: SimpleNamespace(
            dialect=SimpleNamespace(name="sqlite")))
        call = asyncio.create_task(place_map_admission(handler)(
            request=fake_request(gate, gone), session=session, limit=1))
        await entered.wait()
        assert gate.running == 1
        gone.set()
        response = await asyncio.wait_for(call, 2)
        assert response.status_code == CLIENT_CLOSED_STATUS
        assert stopped.is_set() and rollbacks == [True]
        assert gate.running == gate.waiting == 0 and gate.stats["abandoned"] == 1

    asyncio.run(exercise())


def test_disconnected_leader_keeps_computing_for_joined_requests():
    async def exercise():
        gate = PlaceMapGate(max_running=1, max_waiting=2)
        release = asyncio.Event()
        calls = 0

        async def hold():
            await release.wait()
            return Response(content=b"")

        async def handler(*, request, session, limit):
            nonlocal calls
            calls += 1
            return Response(content=b"shared")

        holder = asyncio.create_task(gate.run(("holder",), hold))
        await settle()
        leader_gone, follower_gone = asyncio.Event(), asyncio.Event()
        wrapped = place_map_admission(handler)
        leader = asyncio.create_task(wrapped(request=fake_request(gate, leader_gone), session=None, limit=1))
        await settle()
        follower = asyncio.create_task(wrapped(request=fake_request(gate, follower_gone), session=None, limit=1))
        await settle()
        assert gate.stats["coalesced"] == 1 and gate.waiting == 1
        leader_gone.set()
        await settle()
        # 합류한 요청이 결과를 기다리므로 리더의 대기열 자리를 놓지 않는다.
        assert not leader.done() and gate.waiting == 1 and gate.stats["abandoned"] == 0
        release.set()
        assert (await leader).body == (await follower).body == b"shared"
        assert calls == 1 and (await holder).body == b""

    asyncio.run(exercise())


def test_real_server_socket_close_frees_the_waiting_slot(test_settings):
    """실제 uvicorn·미들웨어(BaseHTTPMiddleware 포함) 사슬에서 연결 끊김이 endpoint까지 닿는지 확인한다."""
    import socket

    import uvicorn

    async def exercise():
        app = create_app(test_settings)
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(app, lifespan="on", log_level="warning"))
        serving = asyncio.create_task(server.serve(sockets=[listener]))
        holder = None
        release = asyncio.Event()
        request = f"GET {PLACES}?kinds=rail_station&limit=5 HTTP/1.1\r\nHost: 127.0.0.1\r\n"
        try:
            await wait_until(lambda: server.started, timeout=30)
            gate = app.state.place_map_gate = PlaceMapGate(max_running=1, max_waiting=1)

            async def hold():
                await release.wait()
                return Response(content=b"")

            holder = asyncio.create_task(gate.run(("holder",), hold))
            await settle()
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write((request + "\r\n").encode())
            await writer.drain()
            await wait_until(lambda: gate.waiting == 1)
            writer.close()
            await writer.wait_closed()
            await wait_until(lambda: gate.waiting == 0 and gate.stats["abandoned"] == 1)
            release.set()
            await holder
            # 빈 대기열 자리로 다음 요청이 정상 처리된다.
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            writer.write((request + "Connection: close\r\n\r\n").encode())
            await writer.drain()
            status_line = await asyncio.wait_for(reader.readline(), 10)
            writer.close()
            await writer.wait_closed()
            assert status_line.startswith(b"HTTP/1.1 200"), status_line
        finally:
            release.set()
            if holder is not None:
                await asyncio.gather(holder, return_exceptions=True)
            server.should_exit = True
            await serving

    asyncio.run(exercise())


def test_disconnect_cancels_a_running_postgres_query(test_settings):
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL 문장 취소 검증")
    from app.db.session import create_engine_and_session_factory

    async def exercise():
        engine, factory = create_engine_and_session_factory(test_settings.database_url)
        gate, gone = PlaceMapGate(), asyncio.Event()
        entered = asyncio.Event()

        async def handler(*, request, session, limit):
            await session.execute(text("SELECT 1"))
            entered.set()
            await session.execute(text("SELECT pg_sleep(5)"))

        try:
            async with factory() as session:
                call = asyncio.create_task(place_map_admission(handler)(
                    request=fake_request(gate, gone), session=session, limit=1))
                await entered.wait()
                await asyncio.sleep(0.1)
                started = asyncio.get_running_loop().time()
                gone.set()
                response = await asyncio.wait_for(call, 3)
                assert response.status_code == CLIENT_CLOSED_STATUS
                assert asyncio.get_running_loop().time() - started < 2
                assert await session.scalar(text("SELECT 1")) == 1
            assert gate.running == 0 and gate.stats["abandoned"] == 1
        finally:
            await engine.dispose()

    asyncio.run(exercise())
