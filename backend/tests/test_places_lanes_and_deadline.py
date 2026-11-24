"""장소 지도 입장 제한의 호출자별 몫(관리·공개)과 25초 시한 대 앞단 30초 여유(PR #273 후속) 회귀 검사."""

import asyncio
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
    place_map_admission,
    run_in_thread_holding,
)

PLACES = "/v1/transport/features/places"
TOKEN = "a" * 40


async def settle(rounds: int = 10) -> None:
    for _ in range(rounds):
        await asyncio.sleep(0)


async def wait_until(condition, timeout: float = 5) -> None:
    async with asyncio.timeout(timeout):
        while not condition():
            await asyncio.sleep(0.005)


def fake_request(gate, headers=None):
    gone = asyncio.Event()

    async def receive():
        await gone.wait()
        return {"type": "http.disconnect"}

    return SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(place_map_gate=gate)), receive=receive,
                           headers=Headers(headers or {}))


def test_lane_needs_admin_token_and_no_gateway_marker():
    gate = PlaceMapGate(admin_token=TOKEN)
    assert gate.lane_for(Headers({"x-transport-admin-token": TOKEN})) == ADMIN
    # 공개 gateway가 덮어쓴 표지는 값과 관계없이(빈 값 포함) 공개다. 토큰이 새어도 공개 몫을 쓴다.
    for marker in ("public", "", "admin"):
        assert gate.lane_for(Headers({"x-transport-admin-token": TOKEN, "x-transport-listener": marker})) == PUBLIC
    assert gate.lane_for(Headers({"x-transport-admin-token": TOKEN[:-1] + "b"})) == PUBLIC
    assert gate.lane_for(Headers({})) == PUBLIC
    assert gate.lane_for(None) == PUBLIC
    # 토큰을 설정하지 않았거나 32자 미만이면 관리 줄이 없고 남겨 둘 몫도 없다.
    for configured in (None, "", "short-token"):
        unconfigured = PlaceMapGate(admin_token=configured, admin_reserved=1)
        assert unconfigured.lane_for(Headers({"x-transport-admin-token": configured or ""})) == PUBLIC
        assert unconfigured.admin_reserved == 0
    with pytest.raises(ValueError):
        PlaceMapGate(max_running=2, admin_reserved=2, admin_token=TOKEN)
    with pytest.raises(ValueError):
        asyncio.run(PlaceMapGate().run(None, lambda: None, lane="other"))


def test_public_flood_cannot_take_the_reserved_admin_slot_and_admin_waiters_go_first():
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
        # 공개 계산이 끝나 슬롯이 비면 먼저 와 있던 공개 대기 요청보다 관리 대기 요청을 먼저 깨운다.
        releases["p1"].set()
        await p1
        await settle()
        assert order == ["p1", "a1", "a2"]
        releases["a1"].set()
        await a1
        await settle()
        assert order == ["p1", "a1", "a2", "p2"]
        for name in ("a2", "p2", "p3"):
            releases[name].set()
        assert [(await task).body for task in (a2, p2, p3)] == [b"a2", b"p2", b"p3"]
        assert gate.running == gate.waiting == 0 and not gate.pending and gate.stats["rejected"] == 2

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
        gate = PlaceMapGate(max_running=2, admin_reserved=1, max_waiting=2, admin_token=TOKEN)
        release = asyncio.Event()
        calls = []

        async def compute(name):
            calls.append(name)
            await release.wait()
            return Response(content=name.encode())

        holder = asyncio.create_task(gate.run(("hold",), lambda: compute("hold"), lane=PUBLIC))
        await settle()
        public = asyncio.create_task(gate.run(("same",), lambda: compute("public"), lane=PUBLIC))
        await settle()
        admin = asyncio.create_task(gate.run(("same",), lambda: compute("admin"), lane=ADMIN))
        await settle()
        assert calls == ["hold", "admin"] and gate.stats["coalesced"] == 0
        release.set()
        assert (await admin).body == b"admin" and (await public).body == b"public"
        await holder

    asyncio.run(exercise())


def test_places_route_classifies_admin_bff_and_public_gateway_requests(test_settings):
    async def exercise():
        app = create_app(test_settings.model_copy(update={"transport_admin_write_token": TOKEN}))
        async with app.router.lifespan_context(app):
            default = app.state.place_map_gate
            assert (default.admin_reserved, default.admin_max_waiting) == (1, 4)
            gate = app.state.place_map_gate = PlaceMapGate(
                max_running=2, admin_reserved=1, max_waiting=0, admin_max_waiting=0, admin_token=TOKEN)
            release = asyncio.Event()

            async def hold():
                await release.wait()
                return Response(content=b"{}")

            # 공개 몫(1건)을 막아 둔다. 공개 대기열 0이라 공개 요청은 곧바로 429다.
            holder = asyncio.create_task(gate.run(("hold",), hold, lane=PUBLIC))
            await settle()
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as http:
                path = f"{PLACES}?kinds=rail_station,airport&limit=5"
                admin = await http.get(path, headers={"x-transport-admin-token": TOKEN})
                via_gateway = await http.get(path, headers={"x-transport-admin-token": TOKEN,
                                                            "x-transport-listener": "public"})
                anonymous = await http.get(path)
                forged = await http.get(path, headers={"x-transport-admin-token": "b" * 40})
            release.set()
            await holder
        assert admin.status_code == 200, admin.text
        assert [response.status_code for response in (via_gateway, anonymous, forged)] == [429, 429, 429]
        assert gate.running == gate.waiting == 0

    asyncio.run(exercise())


def test_lane_settings_reach_the_gate_and_are_bounded(test_settings):
    from pydantic import ValidationError

    async def gate_for(**update):
        app = create_app(test_settings.model_copy(update=update))
        async with app.router.lifespan_context(app):
            return app.state.place_map_gate

    gate = asyncio.run(gate_for(transport_admin_write_token=TOKEN, places_max_running=3,
                                places_admin_reserved_running=2, places_admin_max_waiting=6))
    assert (gate.max_running, gate.admin_reserved, gate.admin_max_waiting) == (3, 2, 6)
    # 동시 1건이면 남길 몫이 없다(공개 요청이 아예 못 도는 설정은 만들지 않는다).
    gate = asyncio.run(gate_for(transport_admin_write_token=TOKEN, places_max_running=1))
    assert gate.admin_reserved == 0
    # 토큰이 없으면 관리 요청을 알아볼 수 없으므로 몫을 남기지 않는다.
    assert asyncio.run(gate_for(transport_admin_write_token=None)).admin_reserved == 0
    assert (test_settings.places_admin_reserved_running, test_settings.places_admin_max_waiting) == (1, 4)
    with pytest.raises(ValidationError):
        type(test_settings).model_validate({**test_settings.model_dump(), "places_admin_reserved_running": 8})


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
                request=fake_request(gate, {"x-transport-admin-token": TOKEN}), session=None, limit=1)

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
    places_location = next(block for block in admin.split("location ") if "features/places" in block.split("{")[0])
    assert marker in places_location
    fuel = (deploy / "transport-fuel" / "api-gateway.conf.template").read_text(encoding="utf-8")
    server_level = fuel.split("location ")[0]
    # server 단계 proxy_set_header는 자체 proxy_set_header가 없는 location에 그대로 이어진다.
    assert marker in server_level
    assert all("proxy_set_header" not in block.split("}")[0] for block in fuel.split("location ")[1:])
