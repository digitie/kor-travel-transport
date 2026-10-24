"""VadaHub SDK의 배편 기준자료를 원천별 마지막 정상 저장본으로 제공한다."""
from __future__ import annotations

import asyncio
import logging
from datetime import UTC, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from fastapi.encoders import jsonable_encoder
from filelock import FileLock, Timeout
from vadahub import LocalArchiveStore, OfficialTerminalClient, VadaHubFileClient, ports_from_features, route_endpoints, terminal_to_port

from app.core.time_utils import now_utc
from app.models import CollectionRun, FerryReferenceSnapshot
from app.schemas import FerryReferenceData, FerryReferenceRow

# 카탈로그의 현재 이력을 찾되 서로 다른 원천을 이름으로 합치지 않는다.
SOURCES = {
    "passenger_routes": ("여객항로", "63", "500059", "psnr_rute_l"),
    "ferry_routes": ("도선항로", "52", "500048", "piltg_rute_l"),
    "ferry_facilities": ("여객선 시설", "3076", "501304", "pssh_p"),
    "official_terminals": ("공식 여객터미널 보완 자료", None, None, None),
}
REFRESH_INTERVAL = timedelta(days=7)
logger = logging.getLogger(__name__)


class VadaHubCollectionService:
    def __init__(self, settings, *, fetcher=None):
        self.settings = settings
        self.fetcher = fetcher

    async def _fetch(self, key: str, *, retry_failed_source: bool = False) -> FerryReferenceData:
        title, dataset_id, layer_id, table = SOURCES[key]
        root = Path(self.settings.vadahub_archive_directory)
        store = LocalArchiveStore(root / "archives")
        # manifest 이전 중단으로 남은 검증된 원문도 재사용한다.
        await store.recover()
        options = {"timeout": 90, "executable_path": self.settings.vadahub_chromium_executable_path}
        with TemporaryDirectory(dir=root) as temporary:
            if key == "official_terminals":
                async with OfficialTerminalClient(**options) as client:
                    receipt = (await store.put(await client.download(Path(temporary) / "terminals.csv"))).receipt
                    terminals = await client.load_file(receipt.local_path, receipt=receipt)
                    rows = [self._port_row(terminal_to_port(item), dict(item.raw_attributes)) if item.name else
                        FerryReferenceRow(record_id=item.record_id, kind="terminal", address=item.address,
                            source_year=str(item.survey_year) if item.survey_year is not None else None,
                            attributes=dict(item.raw_attributes)) for item in terminals]
                    return FerryReferenceData(dataset=key, title=title, source=receipt.source,
                        source_url=receipt.source_url, source_version=receipt.content_date.isoformat(),
                        source_sha256=receipt.sha256, collected_at=receipt.collected_at, items=rows)
            async with VadaHubFileClient(**options) as client:
                datasets = [d for d in await client.list_datasets() if d.dataset_id == dataset_id]
                if len(datasets) != 1:
                    raise ValueError("VadaHub catalog identity changed")
                layers = [l for l in await client.list_layers(datasets[0]) if l.layer_id == layer_id and l.table_name == table]
                if len(layers) != 1:
                    raise ValueError("VadaHub layer identity changed")
                layer = layers[0]
                versions = await store.versions(layer)
                recent = [v for v in versions if now_utc() - v.receipt.collected_at < REFRESH_INTERVAL]
                async def load(receipt):
                    features = await client.load_file(receipt.local_path, layer=layer, receipt=receipt, max_features=5000)
                    if key == "ferry_facilities":
                        ports = ports_from_features(features)
                        rows = [self._port_row(p, dict(p.feature.attributes)) for p in ports]
                    else:
                        rows = []
                        for feature in features:
                            endpoints = route_endpoints(feature)
                            rows.append(FerryReferenceRow(record_id=feature.record_id, kind="route",
                                name=endpoints.route_name, departure=endpoints.departure, arrival=endpoints.arrival,
                                calls=endpoints.calls_raw, segment=endpoints.segment_name,
                                attributes=jsonable_encoder(dict(feature.attributes))))
                    return self._validate(FerryReferenceData(dataset=key, title=title, source=f"vadahub:{table}",
                        source_url=receipt.source_url, source_version=layer.history_date,
                        source_sha256=receipt.sha256, collected_at=receipt.collected_at, items=rows), key)
                if recent:
                    try:
                        return await load(recent[-1].receipt)
                    except Exception:
                        if not retry_failed_source:
                            raise
                receipt = (await store.put(await client.download(layer, Path(temporary) / "source.zip"))).receipt
                return await load(receipt)

    @staticmethod
    def _validate(data: FerryReferenceData, key: str) -> FerryReferenceData:
        if data.dataset != key or not data.items or len(data.items) > 5000:
            raise ValueError("VadaHub incomplete or mismatched dataset")
        if len({r.record_id for r in data.items}) != len(data.items):
            raise ValueError("VadaHub duplicate source identities")
        return data

    @staticmethod
    def _port_row(port, attributes):
        return FerryReferenceRow(record_id=port.port_id, kind=port.kind, name=port.name,
            address=port.address, telephone=port.telephone, source_year=port.source_year,
            attributes=jsonable_encoder(attributes))

    async def collect(self, session):
        if not self.settings.vadahub_collection_enabled:
            return {"status": "skipped", "reason": "VadaHub collection is disabled"}
        root = Path(self.settings.vadahub_archive_directory)
        root.mkdir(parents=True, exist_ok=True)
        lock = FileLock(root / "collection.lock", timeout=0)
        try:
            lock.acquire()
        except Timeout:
            return {"status": "skipped", "reason": "VadaHub collection is already running"}
        try:
            run = CollectionRun(started_at=now_utc(), status="running", trigger="dagster_vadahub")
            session.add(run)
            await session.commit()
            run_id = run.id
            failures = []
            counts = {}
            try:
                for key in SOURCES:
                    old = await session.get(FerryReferenceSnapshot, key)
                    if old and old.response_json and not old.last_error:
                        checked = old.last_attempt_at.replace(tzinfo=UTC) if old.last_attempt_at.tzinfo is None else old.last_attempt_at
                        if now_utc() - checked < REFRESH_INTERVAL:
                            counts[key] = len(old.response_json["items"])
                            await session.commit()
                            continue
                    await session.commit()  # 브라우저 대기 중 DB transaction을 잡지 않는다.
                    attempted_at = now_utc()
                    try:
                        # 이전 오류가 있어도 정상 ZIP은 재사용한다. 최근 ZIP을 실제 검증해
                        # 실패한 경우에만 새 원문을 내려받아 저장 실패 뒤의 비용을 줄인다.
                        value = (await self.fetcher(key) if self.fetcher is not None else
                                 await self._fetch(key, retry_failed_source=bool(old and old.last_error)))
                        data = self._validate(FerryReferenceData.model_validate(value), key)
                    except Exception as exc:
                        failures.append(key)
                        row = await session.get(FerryReferenceSnapshot, key)
                        if row is None:
                            row = FerryReferenceSnapshot(dataset=key)
                            session.add(row)
                        row.last_attempt_at = attempted_at
                        row.last_error = type(exc).__name__
                        await session.commit()
                        continue
                    row = await session.get(FerryReferenceSnapshot, key)
                    if row is None:
                        row = FerryReferenceSnapshot(dataset=key)
                        session.add(row)
                    row.response_json = data.model_dump(mode="json")
                    row.last_attempt_at = attempted_at
                    row.last_error = None
                    await session.commit()
                    counts[key] = len(data.items)
                run = await session.get(CollectionRun, run_id)
                run.status = "partial_success" if failures else "success"
                run.finished_at = now_utc()
                run.error_message = ", ".join(failures) or None
                await session.commit()
            except BaseException:
                try:
                    await session.rollback()
                    run = await session.get(CollectionRun, run_id)
                    run.status = "failed"
                    run.finished_at = now_utc()
                    run.error_message = "VadaHub collection interrupted; committed datasets retained"
                    await session.commit()
                except (Exception, asyncio.CancelledError) as recording_error:
                    logger.warning("VadaHub failure recording failed run_id=%s type=%s", run_id, type(recording_error).__name__)
                    try:
                        await session.rollback()
                    except (Exception, asyncio.CancelledError):
                        logger.warning("VadaHub failure rollback failed run_id=%s", run_id)
                raise
            return {"status": "partial_success" if failures else "success", "run_id": run_id, "counts": counts, "failed_datasets": failures}
        finally:
            lock.release()
