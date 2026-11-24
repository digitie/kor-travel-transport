"""장소 지도 입장 제한의 호출자별 몫(관리·공개)과 25초 시한 대 앞단 30초 여유(PR #273 후속) 회귀 검사."""

import asyncio
import hashlib
import hmac
import logging
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from anyio import CapacityLimiter
from fastapi import HTTPException
from starlette.datastructures import Headers
from starlette.responses import Response

from app.main import create_app
from app.services import place_map_admission as admission
from app.services.place_map_admission import (
    ADMIN,
    PUBLIC,
    TIMEOUT_RETRY_AFTER_SECONDS,
    UPSTREAM_PROXY_TIMEOUT_SECONDS,
    PlaceMapGate,
    admin_lane_proof,
    place_map_admission,
    run_in_thread_holding,
)

PLACES = "/v1/transport/features/places"
TOKEN = "a" * 40
# 관리 BFF(route.ts)와 같은 방식으로 만든 증명. 쓰기 토큰 자체는 조회 경로에 실리지 않는다.
PROOF = hmac.new(TOKEN.encode(), b"places-admin-lane", hashlib.sha256).hexdigest()
LANE = "x-transport-places-lane"


async def settle(rounds: int = 10) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def wait_until(condition, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


def fake_request(gate, headers=None, peer="127.0.0.1"):
    gone = asyncio.Event()

    async def receive():
        await gone.wait()
        return {"type": "http.disconnect"}

    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(place_map_gate=gate)), receive=receive,
                           headers=Headers(headers or {}), client=SimpleNamespace(host=peer))


def test_admin_lane_needs_derived_proof_loopback_peer_and_no_public_markers():
    gate = PlaceMapGate(admin_token=TOKEN)
    assert admin_lane_proof(TOKEN) == PROOF.encode()
    assert gate.lane_for(Headers({LANE: PROOF}), "127.0.0.1") == ADMIN
    assert gate.lane_for(Headers({LANE: PROOF}), "::1") == ADMIN
    # 쓰기 토큰 자체는 관리 줄 증명이 아니다(지도 조회 경로에 쓰기 토큰을 싣지 않는다).
    assert gate.lane_for(Headers({LANE: TOKEN}), "127.0.0.1") == PUBLIC
    assert gate.lane_for(Headers({"x-transport-admin-token": TOKEN}), "127.0.0.1") == PUBLIC
    # 공개 gateway·공개 BFF가 덮어쓴 표지는 값과 관계없이(빈 값 포함) 공개다. 증명이 새어도 공개 몫을 쓴다.
    for marker in ("public", "", "admin"):
        assert gate.lane_for(Headers({LANE: PROOF, "x-transport-listener": marker}), "127.0.0.1") == PUBLIC
    # gateway를 거친 요청(forwarded header)·loopback 밖 peer·peer 모름은 공개다.
    for forwarded in ({"x-forwarded-for": "203.0.113.9"}, {"forwarded": "for=203.0.113.9"}, {"x-forwarded-for": ""}):
        assert gate.lane_for(Headers({LANE: PROOF, **forwarded}), "127.0.0.1") == PUBLIC
    for peer in ("192.168.1.13", None, "not-an-ip"):
        assert gate.lane_for(Headers({LANE: PROOF}), peer) == PUBLIC
    assert gate.lane_for(Headers({LANE: PROOF[:-1] + "0"}), "127.0.0.1") == PUBLIC
    assert gate.lane_for(Headers({}), "127.0.0.1") == PUBLIC
    assert gate.lane_for(None, "127.0.0.1") == PUBLIC
    # 토큰을 설정하지 않았거나 32자 미만이면 관리 줄이 없고 남겨 둘 몫도 없다.
    for configured in (None, "", "short-token"):
        unconfigured = PlaceMapGate(admin_token=configured, admin_reserved=1)
        assert admin_lane_proof(configured) is None and not unconfigured.admin_lane_enabled
        assert unconfigured.lane_for(Headers({LANE: PROOF}), "127.0.0.1") == PUBLIC
        assert unconfigured.admin_reserved == 0
    with pytest.raises(ValueError):
        PlaceMapGate(max_running=2, admin_reserved=2, admin_token=TOKEN)
    with pytest.raises(ValueError):
        asyncio.run(PlaceMapGate().run(None, lambda: None, lane="other"))


def test_public_flood_cannot_take_the_reserved_admin_slot_and_admin_cannot_take_the_public_minimum():
    async def exercise():
        gate = PlaceMapGate(max_running=2, admin_reserved=1, max_waiting=2, admin_max_waiting=1, admin_token=TOKEN)
        releases = {name: asyncio.Event() for name in ("p1", "p2", "p3", "a1", "a2")}
        order = []

        async def compute(name):
            order.append(name)
            await releases[name].wait()
            return Response(content=name.encode())

        def start(name, lane):
            return asyncio.create_task(gate.run((name,), lambda: compute(name), lane=lane))

        p1 = start("p1", PUBLIC)
        await settle()
        p2, p3 = start("p2", PUBLIC), start("p3", PUBLIC)
        await settle()
        # 공개 몫(2 - 1 = 1건)이 찼다. 남은 한 슬롯은 비어 있어도 공개 요청은 기다린다.
        assert order == ["p1"] and gate.lane_running(PUBLIC) == 1 and gate.lane_waiting(PUBLIC) == 2
        with pytest.raises(HTTPException) as rejected:
            await gate.run(("p4",), lambda: compute("p4"), lane=PUBLIC)
        assert rejected.value.status_code == 429
        # 관리 요청은 공개 대기열이 가득 차도 남겨 둔 슬롯에서 바로 시작한다.
        a1 = start("a1", ADMIN)
        await settle()
        assert order == ["p1", "a1"] and gate.running == 2
        # 관리 대기열은 따로 센다(1건). 넘치면 관리 요청도 429다.
        a2 = start("a2", ADMIN)
        await settle()
        assert gate.lane_waiting(ADMIN) == 1
        with pytest.raises(HTTPException) as admin_rejected:
            await gate.run(("a3",), lambda: compute("a3"), lane=ADMIN)
        assert admin_rejected.value.status_code == 429
        # 공개 계산이 끝나 빈 슬롯은 공개 최소 몫이다. 공개가 기다리는 동안 관리는 남겨 둔 1건을 넘겨 시작하지 않는다.
        releases["p1"].set()
        await p1
        await settle()
        assert order == ["p1", "a1", "p2"]
        # 관리 계산이 끝나 빈 남겨 둔 슬롯은 기다리던 관리 요청이 먼저 받는다.
        releases["a1"].set()
        await a1
        await settle()
        assert order == ["p1", "a1", "p2", "a2"]
        for name in ("a2", "p2", "p3"):
            releases[name].set()
        assert [(await task).body for task in (a2, p2, p3)] == [b"a2", b"p2", b"p3"]
        assert gate.running == gate.waiting == 0 and not gate.pending and gate.stats["rejected"] == 2

    asyncio.run(exercise())


def test_admin_burst_does_not_starve_waiting_public_requests_past_the_deadline():
    """관리 목록 8건이 한꺼번에 와도 기다리는 공개 요청은 시한 안에 처리된다(Popper P1)."""
    async def exercise():
        work = 0.4
        gate = PlaceMapGate(max_running=4, admin_reserved=1, max_waiting=8, admin_max_waiting=8,
                            deadline_seconds=1.0, admin_token=TOKEN)
        finished = {}
        loop = asyncio.get_running_loop()
        began = loop.time()

        async def compute(name):
            await asyncio.sleep(work)
            finished[name] = loop.time() - began
            return Response(content=name.encode())

        admins = [asyncio.create_task(gate.run((f"a{n}",), lambda n=n: compute(f"a{n}"), lane=ADMIN)) for n in range(8)]
        await settle()
        # 공개가 기다리지 않는 동안 관리는 공개 최소 몫(1슬롯)을 남기고 3건까지 시작한다.
        assert gate.lane_running(ADMIN) == 3 and gate.lane_waiting(ADMIN) == 5
        publics = [asyncio.create_task(gate.run((f"p{n}",), lambda n=n: compute(f"p{n}"), lane=PUBLIC)) for n in range(2)]
        await settle()
        assert gate.lane_running(PUBLIC) == 1 and gate.lane_waiting(PUBLIC) == 1
        results = await asyncio.gather(*publics, return_exceptions=True)
        assert all(isinstance(result, Response) for result in results), results
        # 첫 공개 요청은 남은 공개 슬롯에서 바로, 둘째는 첫 물결 뒤(≈ 2 × 작업 시간 = 0.8초)에 끝난다. 관리 우선
        # 깨우기에 관리 상한이 없던 때는 관리 둘째 물결 4건이 먼저 들어가 둘째 공개 요청이 ≈ 1.2초에 시한(1초)을 넘겼다.
        assert finished["p0"] < 0.6 and finished["p1"] < 1.0
        admin_results = await asyncio.gather(*admins, return_exceptions=True)
        # 관리 요청도 결국 모두 끝난다(이 짧은 시한에서는 마지막 물결이 504일 수 있다).
        assert all(isinstance(result, Response) or getattr(result, "status_code", None) == 504 for result in admin_results)
        assert gate.running == gate.waiting == 0 and not gate.pending

    asyncio.run(exercise())


def test_admin_alone_may_use_all_but_the_public_minimum_and_single_slot_is_shared():
    async def exercise():
        release = asyncio.Event()

        async def hold():
            await release.wait()
            return Response(content=b"")

        gate = PlaceMapGate(max_running=4, admin_reserved=1, admin_token=TOKEN)
        admins = [asyncio.create_task(gate.run((n,), hold, lane=ADMIN)) for n in range(4)]
        await settle()
        assert gate.lane_running(ADMIN) == 3 and gate.lane_waiting(ADMIN) == 1
        public = asyncio.create_task(gate.run(("p",), hold, lane=PUBLIC))
        await settle()
        assert gate.lane_running(PUBLIC) == 1
        release.set()
        await asyncio.gather(*admins, public)
        # 동시 1건 설정에서는 공개 최소 몫이 없다. 관리·공개가 한 슬롯을 나눈다.
        single = PlaceMapGate(max_running=1, admin_reserved=0, admin_token=TOKEN)
        release.clear()
        first = asyncio.create_task(single.run(("a",), hold, lane=ADMIN))
        await settle()
        assert single.lane_running(ADMIN) == 1
        release.set()
        await first

    asyncio.run(exercise())


def test_cancelled_waiters_do_not_leak_lane_slots():
    async def exercise():
        gate = PlaceMapGate(max_running=2, admin_reserved=1, max_waiting=4, admin_token=TOKEN)
        release = asyncio.Event()

        async def hold():
            await release.wait()
            return Response(content=b"")

        holders = [asyncio.create_task(gate.run((n,), hold, lane=lane)) for n, lane in ((1, PUBLIC), (2, ADMIN))]
        await settle()
        waiters = [asyncio.create_task(gate.run((n,), hold, lane=lane)) for n, lane in ((3, PUBLIC), (4, ADMIN))]
        await settle()
        assert gate.waiting == 2
        for task in waiters:
            task.cancel()
        await asyncio.gather(*waiters, return_exceptions=True)
        assert gate.waiting == 0 and not gate.pending
        release.set()
        await asyncio.gather(*holders)
        assert gate.running == 0
        # 슬롯이 모두 돌아왔다: 공개 1건 + 관리 1건이 다시 바로 시작한다.
        release.clear()
        again = [asyncio.create_task(gate.run((n,), hold, lane=lane)) for n, lane in ((5, PUBLIC), (6, ADMIN))]
        await settle()
        assert gate.lane_running(PUBLIC) == 1 and gate.lane_running(ADMIN) == 1 and gate.waiting == 0
        release.set()
        await asyncio.gather(*again)

    asyncio.run(exercise())


def test_admin_requests_do_not_join_a_waiting_public_leader():
    async def exercise():
        gate = PlaceMapGate(max_running=3, admin_reserved=1, max_waiting=2, admin_token=TOKEN)
        release = asyncio.Event()
        calls = []

        async def compute(name):
            calls.append(name)
            await release.wait()
            return Response(content=name.encode())

        holders = [asyncio.create_task(gate.run((f"hold{n}",), lambda n=n: compute(f"hold{n}"), lane=PUBLIC))
                   for n in range(2)]
        await settle()
        public = asyncio.create_task(gate.run(("same",), lambda: compute("public"), lane=PUBLIC))
        await settle()
        admin = asyncio.create_task(gate.run(("same",), lambda: compute("admin"), lane=ADMIN))
        await settle()
        assert calls == ["hold0", "hold1", "admin"] and gate.stats["coalesced"] == 0
        release.set()
        assert (await admin).body == b"admin" and (await public).body == b"public"
        await asyncio.gather(*holders)

    asyncio.run(exercise())


def test_places_route_classifies_admin_bff_and_public_requests(test_settings):
    async def exercise():
        app = create_app(test_settings.model_copy(update={"transport_admin_write_token": TOKEN}))
        async with app.router.lifespan_context(app):
            default = app.state.place_map_gate
            assert (default.admin_reserved, default.admin_max_waiting, default.admin_lane_enabled) == (1, 4, True)
            gate = app.state.place_map_gate = PlaceMapGate(
                max_running=2, admin_reserved=1, max_waiting=0, admin_max_waiting=0, admin_token=TOKEN)
            release = asyncio.Event()

            async def hold():
                await release.wait()
                return Response(content=b"{}")

            # 공개 몫(1건)을 막아 둔다. 공개 대기열 0이라 공개 요청은 곧바로 429다.
            holder = asyncio.create_task(gate.run(("hold",), hold, lane=PUBLIC))
            await settle()
            # ASGI 시험 client의 peer는 127.0.0.1이다(관리 BFF가 loopback backend를 직접 부르는 것과 같다).
            transport = httpx.ASGITransport(app=app, client=("127.0.0.1", 50000))
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                path = f"{PLACES}?kinds=rail_station,airport&limit=5"
                admin = await http.get(path, headers={LANE: PROOF})
                rejected = [
                    await http.get(path, headers={LANE: PROOF, "x-transport-listener": "public"}),
                    await http.get(path, headers={LANE: PROOF, "x-forwarded-for": "203.0.113.9"}),
                    await http.get(path),
                    await http.get(path, headers={"x-transport-admin-token": TOKEN}),
                    await http.get(path, headers={LANE: "b" * 64}),
                ]
            remote = httpx.ASGITransport(app=app, client=("192.168.1.50", 50000))
            async with httpx.AsyncClient(transport=remote, base_url="http://testserver") as http:
                rejected.append(await http.get(f"{PLACES}?kinds=rail_station,airport&limit=5", headers={LANE: PROOF}))
            release.set()
            await holder
        assert admin.status_code == 200, admin.text
        assert [response.status_code for response in rejected] == [429] * 6
        assert gate.running == gate.waiting == 0

    asyncio.run(exercise())


def test_lane_settings_reach_the_gate_are_validated_and_logged(test_settings, caplog):
    from pydantic import ValidationError

    async def gate_for(**update):
        app = create_app(test_settings.model_copy(update=update))
        async with app.router.lifespan_context(app):
            return app.state.place_map_gate

    with caplog.at_level(logging.INFO, logger="app.main"):
        gate = asyncio.run(gate_for(transport_admin_write_token=TOKEN, places_max_running=3,
                                    places_admin_reserved_running=2, places_admin_max_waiting=6))
    assert (gate.max_running, gate.admin_reserved, gate.admin_max_waiting) == (3, 2, 6)
    configured = [record.getMessage() for record in caplog.records if "places_admission_configured" in record.getMessage()]
    assert configured and "public_max_running=1" in configured[-1] and "admin_lane=enabled" in configured[-1]
    # 동시 1건이면 남길 몫이 없다(관리·공개가 한 슬롯을 나눈다).
    gate = asyncio.run(gate_for(transport_admin_write_token=TOKEN, places_max_running=1))
    assert gate.admin_reserved == 0
    # 토큰이 없으면 관리 요청을 알아볼 수 없으므로 몫을 남기지 않는다.
    caplog.clear()
    with caplog.at_level(logging.INFO, logger="app.main"):
        assert asyncio.run(gate_for(transport_admin_write_token=None)).admin_reserved == 0
    assert any("admin_lane=disabled" in record.getMessage() and "admin_reserved=0" in record.getMessage()
               for record in caplog.records)
    assert (test_settings.places_admin_reserved_running, test_settings.places_admin_max_waiting) == (1, 4)
    Settings = type(test_settings)
    with pytest.raises(ValidationError):
        Settings.model_validate({**test_settings.model_dump(), "places_admin_reserved_running": 8})
    # 공개가 한 건도 못 도는 조합은 조용히 줄이지 않고 거절한다.
    with pytest.raises(ValidationError, match="PLACES_ADMIN_RESERVED_RUNNING"):
        Settings.model_validate({**test_settings.model_dump(), "places_max_running": 3,
                                 "places_admin_reserved_running": 3})
    assert Settings.model_validate({**test_settings.model_dump(), "places_max_running": 1,
                                    "places_admin_reserved_running": 1}).places_max_running == 1


# --- 25초 시한 대 앞단 30초: 504가 시한 직후에 나가는지 -------------------------------------------------

DEADLINE = 0.4
#: 시한 뒤 504까지 허용하는 지연(초). CI 부하를 감안한 상한이며, 운영 여유(30 - 25 = 5초)보다 훨씬 작다.
EMIT_SLACK = 0.35


def test_504_is_emitted_at_the_deadline_while_thread_validation_is_still_running(caplog):
    async def exercise():
        gate = PlaceMapGate(deadline_seconds=DEADLINE)
        limiter = CapacityLimiter(1)
        started, finish = threading.Event(), threading.Event()

        def validate():
            # 멈출 수 없는 thread 검증이 시한을 크게 넘겨 돈다.
            started.set()
            finish.wait(10)
            return b"[]", 0

        async def handler(*, request, session, limit):
            # SQL을 시한 직전까지 쓰고(가정) 그 뒤 thread 검증을 시작한다.
            await asyncio.sleep(DEADLINE - 0.05)
            await run_in_thread_holding(limiter, validate)
            return Response(content=b"late")

        wrapped = place_map_admission(handler)
        loop = asyncio.get_running_loop()
        began = loop.time()
        with pytest.raises(HTTPException) as caught:
            await wrapped(request=fake_request(gate), session=None, limit=1)
        elapsed = loop.time() - began
        assert started.is_set() and not finish.is_set()
        # 응답은 thread를 기다리지 않는다. thread는 limiter 토큰을 쥔 채 끝까지 돌고, 끝날 때 반납한다.
        assert limiter.borrowed_tokens == 1
        finish.set()
        await wait_until(lambda: limiter.borrowed_tokens == 0)
        return caught.value, elapsed

    with caplog.at_level(logging.WARNING, logger="app.services.place_map_admission"):
        error, elapsed = asyncio.run(exercise())
    assert error.status_code == 504 and error.headers == {"Retry-After": str(TIMEOUT_RETRY_AFTER_SECONDS)}
    assert DEADLINE <= elapsed < DEADLINE + EMIT_SLACK
    logged = [record.getMessage() for record in caplog.records if "places_deadline_exceeded" in record.getMessage()]
    assert len(logged) == 1 and "role=leader" in logged[0] and "lane=public" in logged[0]
    elapsed_ms = float(logged[0].split("elapsed_ms=")[1].split()[0])
    margin_ms = float(logged[0].split("proxy_margin_ms=")[1].split()[0])
    assert DEADLINE * 1000 <= elapsed_ms < (DEADLINE + EMIT_SLACK) * 1000
    assert margin_ms == pytest.approx(UPSTREAM_PROXY_TIMEOUT_SECONDS * 1000 - elapsed_ms, abs=1)


def test_stuck_rollback_after_the_deadline_is_bounded(monkeypatch, caplog):
    monkeypatch.setattr(admission, "TIMEOUT_CLEANUP_GRACE_SECONDS", 0.1)

    class StuckSession:
        rolled_back = False

        def get_bind(self):
            return SimpleNamespace(dialect=SimpleNamespace(name="sqlite"))

        async def rollback(self):
            # 서버가 응답하지 않는 rollback. 상한이 없으면 앞단 30초를 넘긴다.
            await asyncio.sleep(30)
            self.rolled_back = True

    async def exercise():
        gate = PlaceMapGate(deadline_seconds=0.2)
        session = StuckSession()

        async def handler(*, request, session, limit):
            await asyncio.sleep(10)

        loop = asyncio.get_running_loop()
        began = loop.time()
        with pytest.raises(HTTPException) as caught:
            await place_map_admission(handler)(request=fake_request(gate), session=session, limit=1)
        return caught.value, loop.time() - began, session

    with caplog.at_level(logging.WARNING, logger="app.services.place_map_admission"):
        error, elapsed, session = asyncio.run(exercise())
    assert error.status_code == 504 and not session.rolled_back
    assert 0.3 <= elapsed < 0.3 + EMIT_SLACK
    messages = " ".join(record.getMessage() for record in caplog.records)
    assert "places_timeout_cleanup_slow" in messages and "places_deadline_exceeded" in messages


def test_admin_lane_deadline_log_names_the_lane(caplog):
    async def exercise():
        gate = PlaceMapGate(deadline_seconds=0.05, admin_token=TOKEN)

        async def handler(*, request, session, limit):
            await asyncio.sleep(5)

        with pytest.raises(HTTPException):
            await place_map_admission(handler)(
                request=fake_request(gate, {LANE: PROOF}), session=None, limit=1)

    with caplog.at_level(logging.WARNING, logger="app.services.place_map_admission"):
        started = time.monotonic()
        asyncio.run(exercise())
        assert time.monotonic() - started < 2
    assert any("lane=admin" in record.getMessage() and "elapsed_ms=" in record.getMessage()
               for record in caplog.records)


def test_public_gateways_overwrite_the_listener_marker_for_places():
    """공개 gateway 두 곳이 places로 가는 요청에 표지를 덮어쓴다(클라이언트가 보낸 같은 header는 nginx가 대신한다)."""
    from pathlib import Path

    deploy = Path(__file__).resolve().parents[2] / "deploy"
    marker = "proxy_set_header X-Transport-Listener public;"
    admin = (deploy / "transport-admin" / "api-gateway.conf.template").read_text(encoding="utf-8")
    # 정확 일치 location(공개 limit 상한)과 정규식 location 모두 — 어느 쪽이 고르든 표지가 붙는다.
    places_locations = [block for block in admin.split("location ")[1:] if "features/places" in block.split("{")[0]]
    assert len(places_locations) >= 2
    for block in places_locations:
        assert marker in block
    fuel = (deploy / "transport-fuel" / "api-gateway.conf.template").read_text(encoding="utf-8")
    server_level = fuel.split("location ")[0]
    # server 단계 proxy_set_header는 자체 proxy_set_header가 없는 location에 그대로 이어진다.
    assert marker in server_level
    assert all("proxy_set_header" not in block.split("}")[0] for block in fuel.split("location ")[1:])


def _pool_events(engine):
    from sqlalchemy import event

    seen = {"invalidate": 0, "checkin": 0, "reset": 0}
    for name in seen:
        event.listen(engine.sync_engine.pool, name, lambda *args, _name=name: seen.__setitem__(_name, seen[_name] + 1))
    return seen


@pytest.mark.parametrize("path", ["deadline", "disconnect", "stuck_rollback"])
def test_real_pool_connection_is_returned_or_invalidated_after_cancel(test_settings, monkeypatch, path):
    """시한·끊김·rollback 상한 경로 모두 풀(1개) 연결을 돌려주고, 상한으로 rollback을 끊으면 그 연결은 버린다(Popper P2-6)."""
    if not test_settings.database_url.startswith("postgresql"):
        pytest.skip("실제 PostgreSQL 풀 반납·무효화 검증")
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    async def exercise():
        engine = create_async_engine(test_settings.database_url, pool_size=1, max_overflow=0, pool_timeout=5)
        factory = async_sessionmaker(engine, expire_on_commit=False)
        seen = _pool_events(engine)
        entered, gone = asyncio.Event(), asyncio.Event()

        async def sleeper(*, request, session, limit):
            await session.execute(text("SELECT 1"))
            entered.set()
            await session.execute(text("SELECT pg_sleep(5)"))

        gate = PlaceMapGate(deadline_seconds=0.4 if path != "disconnect" else 5)
        request = fake_request(gate)
        if path == "disconnect":
            async def receive():
                await gone.wait()
                return {"type": "http.disconnect"}
            request.receive = receive
        try:
            async with factory() as session:
                if path == "stuck_rollback":
                    monkeypatch.setattr(admission, "TIMEOUT_CLEANUP_GRACE_SECONDS", 0.05)
                    original = session.rollback

                    async def slow_rollback():
                        await asyncio.sleep(1)
                        await original()
                    monkeypatch.setattr(session, "rollback", slow_rollback)
                call = asyncio.create_task(place_map_admission(sleeper)(request=request, session=session, limit=1))
                await asyncio.wait_for(entered.wait(), 5)
                if path == "disconnect":
                    await asyncio.sleep(0.1)
                    gone.set()
                started = time.monotonic()
                outcome = await asyncio.gather(call, return_exceptions=True)
                assert time.monotonic() - started < 2
                if path == "disconnect":
                    assert outcome[0].status_code == 499
                else:
                    assert getattr(outcome[0], "status_code", None) == 504
            # session 종료 뒤 풀에 빌린 연결이 없다.
            assert engine.sync_engine.pool.checkedout() == 0
            # 다음 요청이 유일한 연결로 바로 성공한다(무효화됐다면 새 연결을 연다).
            async with factory() as session:
                assert await asyncio.wait_for(session.scalar(text("SELECT 1")), 3) == 1
            assert engine.sync_engine.pool.checkedout() == 0
            return dict(seen)
        finally:
            await engine.dispose()

    seen = asyncio.run(exercise())
    # 문장 도중 취소된 연결은 SQLAlchemy가 무효화한다(서버 쪽 상태를 모르는 연결을 풀에 되돌리지 않는다).
    # 그 뒤 다음 요청은 새 연결로 성공하고 둘 다 풀에 돌아온다.
    assert seen["invalidate"] == 1 and seen["checkin"] == 2
