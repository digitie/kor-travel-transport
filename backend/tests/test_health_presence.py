"""health 응답은 행 존재 여부만 읽으며 DB 실패를 정상으로 바꾸지 않는다."""
import asyncio

import httpx
import pytest
from sqlalchemy import event, text
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.core.config import Settings
from app.main import create_app


def _health_app(tmp_path):
    app = create_app(Settings(
        database_url=f"sqlite+aiosqlite:///{tmp_path / 'health-only.sqlite3'}",
        seed_sample_data=False, enable_scheduler=False, release_sha="health-test",
    ))
    route = next(route for route in app.routes if getattr(route, "path", None) == "/health")
    return app, route.dependant.dependencies[0].call


@pytest.mark.parametrize("rows", [0, 1, 1024])
def test_health_seeded_checks_presence_without_count(tmp_path, rows):
    async def scenario():
        app, dependency = _health_app(tmp_path)
        engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'presence.sqlite3'}")
        try:
            async with engine.begin() as connection:
                # 실제 endpoint가 읽는 열만 있는 독립 DB다. 운영/공유 fixture를 사용하지 않는다.
                await connection.execute(text("CREATE TABLE parking_snapshots (id INTEGER PRIMARY KEY)"))
                if rows:
                    await connection.execute(
                        text("INSERT INTO parking_snapshots (id) VALUES (:id)"),
                        [{"id": n + 1} for n in range(rows)],
                    )
            observed = []
            event.listen(engine.sync_engine, "before_cursor_execute",
                         lambda conn, cursor, statement, params, context, many: observed.append(statement))

            async def session():
                async with AsyncSession(engine) as value:
                    yield value

            app.dependency_overrides[dependency] = session
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver") as client:
                response = await client.get("/health")
            assert response.status_code == 200
            assert response.json() == {
                "status": "ok", "database": "ready", "seeded": bool(rows), "release_sha": "health-test",
            }
            assert len(observed) == 1
            assert "exists" in observed[0].lower()
            assert "count(" not in observed[0].lower()
        finally:
            await engine.dispose()
    asyncio.run(scenario())


def test_health_database_error_is_not_healthy(tmp_path):
    app, dependency = _health_app(tmp_path)

    class FailedSession:
        async def scalar(self, statement):
            raise OperationalError("unavailable", {}, RuntimeError("database unavailable"))

    async def failed():
        yield FailedSession()

    app.dependency_overrides[dependency] = failed

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://testserver",
        ) as client:
            response = await client.get("/health")
        assert response.status_code == 500
        assert response.headers["content-type"].startswith("application/problem+json")
        assert response.json() == {"type": "about:blank", "title": "Internal Server Error", "status": 500, "detail": "서버 내부 오류가 발생했습니다.", "instance": "/health"}
        assert "database unavailable" not in response.text
    asyncio.run(scenario())
