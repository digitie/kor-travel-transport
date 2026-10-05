"""Dagster op 실패가 공용 event log(dagster_shared, 전 테넌트 UI)로 provider 키를 내보내지 않는다.

op에서 빠져나간 예외는 Dagster가 `str(exc)`·traceback·`__cause__`/`__context__` 사슬째 직렬화해 공용
event log에 남긴다. code-server는 `app.main`의 logging filter를 import하지 않으므로 op 경계에서 가린다.
"""

from __future__ import annotations

from typing import Any

import pytest
from dagster import DagsterEventType

from app.core.config import Settings
from app.dagster import definitions as dagster_definitions
from app.dagster.recovery import CollectionLeaseLost

DATA_GO_KR_KEY = "FAKEdataGoKrKey%2Bz9Q=="
KEX_KEY = "FAKEkexKey7777"
KRIC_KEY = "FAKEkricKey8888"
VWORLD_KEY = "FAKEvworldKey9999"
KAKAO_KEY = "FAKEkakaoKey0000"
SECRETS = (DATA_GO_KR_KEY, KEX_KEY, KRIC_KEY, VWORLD_KEY, KAKAO_KEY)
URL_ONLY_KEY = "FAKEurlOnlyKey5555"  # 설정에 없는 키도 URL의 serviceKey= 값은 가린다.


def _leaky_error() -> Exception:
    """provider 예외처럼 URL·키를 담고, 원인 사슬에도 다른 키를 담는다."""
    try:
        raise ValueError(f"upstream said: kex key {KEX_KEY} / kric {KRIC_KEY} / kakao KakaoAK {KAKAO_KEY}")
    except ValueError as inner:
        try:
            raise ConnectionError(
                "GET https://apis.data.go.kr/B551177/x?serviceKey="
                f"{URL_ONLY_KEY}&pageNo=1 failed; raw {DATA_GO_KR_KEY}; vworld key={VWORLD_KEY}"
            ) from inner
        except ConnectionError as outer:
            return outer


class _AnyService:
    def __init__(self, _settings: Any) -> None:
        pass

    def __getattr__(self, _name: str):
        async def call(*_args: Any, **_kwargs: Any) -> None:
            return None

        return call


def _secret_settings() -> Settings:
    return Settings(
        database_url="sqlite+aiosqlite:///unused.sqlite3",
        scheduler_mode="dagster",
        data_go_kr_service_key=DATA_GO_KR_KEY,
        kex_ex_api_key=KEX_KEY,
        kric_service_key=KRIC_KEY,
        vworld_api_key=VWORLD_KEY,
        kakao_rest_api_key=KAKAO_KEY,
    )


def _patch_services(monkeypatch) -> None:
    for name in (
        "CollectionService", "TransportCollectionService", "RailMaritimeCollectionService",
        "BusReferenceCollectionService", "PlaceLocationCollectionService", "KakaoPlaceCollectionService",
        "KricTimetableCollectionService", "RestAreaCollectionService",
    ):
        monkeypatch.setattr(dagster_definitions, name, _AnyService)
    monkeypatch.setattr(dagster_definitions, "_settings", _secret_settings)
    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)


def _error_texts(error_info) -> list[str]:
    """Dagster SerializableErrorInfo의 message·stack과 cause/context 사슬 전체."""
    texts: list[str] = []
    while error_info is not None:
        texts.append(error_info.message)
        texts.extend(error_info.stack)
        texts.extend(_error_texts(error_info.context))
        error_info = error_info.cause
    return texts


def _exception_texts(error: BaseException | None) -> list[str]:
    texts: list[str] = []
    seen: set[int] = set()
    pending = [error]
    while pending:
        current = pending.pop()
        if current is None or id(current) in seen:
            continue
        seen.add(id(current))
        texts.append(f"{type(current).__name__}: {current}")
        pending.extend([current.__cause__, current.__context__])
    return texts


def _assert_no_secret(texts: list[str]) -> None:
    joined = "\n".join(texts)
    for secret in (*SECRETS, URL_ONLY_KEY):
        assert secret not in joined


#: (job, 실패를 기대하는 op) — 모든 수집 op를 덮는다. enrich op는 아래에서 따로 본다.
JOB_FIRST_OPS = [
    ("airport_collection_job", "collect_airport_parking"),
    ("highway_collection_job", "collect_highway_transport"),
    ("fuel_collection_job", "collect_fuel_transport"),
    ("rail_reference_collection_job", "collect_rail_reference"),
    ("maritime_reference_collection_job", "collect_maritime_reference"),
    ("ferry_timetable_collection_job", "collect_ferry_timetable"),
    ("bus_reference_collection_job", "collect_bus_reference"),
    ("place_location_collection_job", "collect_place_locations"),
    ("kakao_place_location_collection_job", "collect_kakao_place_locations"),
    ("kric_timetable_collection_job", "collect_kric_timetable"),
    ("rest_area_reference_collection_job", "collect_rest_area_reference"),
    ("rest_area_fuel_price_collection_job", "collect_rest_area_fuel_prices"),
]


@pytest.mark.parametrize(("job_name", "op_name"), JOB_FIRST_OPS)
def test_op_crash_reaches_event_log_without_provider_keys(monkeypatch, job_name, op_name):
    async def leaky_run(*_args: Any, **_kwargs: Any):
        raise _leaky_error()

    _patch_services(monkeypatch)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", leaky_run)
    job = getattr(dagster_definitions, job_name)
    result = job.execute_in_process(raise_on_error=False)

    assert result.success is False
    assert not any(event.is_step_up_for_retry for event in result.all_events)
    failures = [event for event in result.all_events if event.event_type == DagsterEventType.STEP_FAILURE]
    assert [event.step_key for event in failures] == [op_name]
    failure_data = failures[0].step_failure_data
    texts = _error_texts(failure_data.error)
    user_failure = failure_data.user_failure_data
    assert user_failure is not None
    texts.append(str(user_failure.description))
    texts.extend(str(value.value) for value in user_failure.metadata.values())
    assert user_failure.metadata["error_type"].value == "builtins.ConnectionError"
    # 공용 event log에 실제로 쓰이는 사건(로그 메시지 포함) 전부를 본다.
    texts.extend(str(event.message) for event in result.all_events)
    _assert_no_secret(texts)
    # 원래 오류 종류와 가린 내용은 진단을 위해 남는다.
    joined = "\n".join(texts)
    assert "ConnectionError" in joined
    assert "serviceKey=<redacted>" in joined


@pytest.mark.parametrize(("job_name", "op_name"), JOB_FIRST_OPS[:3])
def test_raised_op_error_chain_has_no_provider_keys(monkeypatch, job_name, op_name):
    async def leaky_run(*_args: Any, **_kwargs: Any):
        raise _leaky_error()

    _patch_services(monkeypatch)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", leaky_run)
    with pytest.raises(Exception) as raised:
        getattr(dagster_definitions, job_name).execute_in_process()
    _assert_no_secret(_exception_texts(raised.value))


def test_enrichment_op_crash_is_redacted(monkeypatch):
    calls: list[str] = []

    async def run(_settings, action, *_args: Any, **_kwargs: Any):
        calls.append("call")
        if len(calls) == 1:
            return {"status": "success", "run_id": 1}
        # enrich op이 그대로 다시 던지는 유일한 예외. 원인 사슬에 키가 남아도 경계에서 가린다.
        try:
            raise _leaky_error()
        except ConnectionError as exc:
            raise CollectionLeaseLost(f"lease lost {KEX_KEY}") from exc

    _patch_services(monkeypatch)
    monkeypatch.setattr(dagster_definitions, "_run_with_session", run)
    result = dagster_definitions.bus_reference_collection_job.execute_in_process(raise_on_error=False)
    assert result.success is False
    failures = [event for event in result.all_events if event.event_type == DagsterEventType.STEP_FAILURE]
    assert [event.step_key for event in failures] == ["enrich_new_reference_locations"]
    texts = _error_texts(failures[0].step_failure_data.error)
    texts.extend(str(event.message) for event in result.all_events)
    _assert_no_secret(texts)
    assert "CollectionLeaseLost" in "\n".join(texts)


def test_boundary_reraises_sanitized_failure_without_chain(monkeypatch):
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)

    @dagster_definitions._redact_op_errors
    def body() -> None:
        raise _leaky_error()

    with pytest.raises(Failure) as raised:
        body()
    error = raised.value
    assert error.__cause__ is None
    assert error.__context__ is None
    assert error.__suppress_context__ is True
    assert error.allow_retries is False
    assert error.description.startswith("builtins.ConnectionError: ")
    assert error.metadata["error_type"].value == "builtins.ConnectionError"
    _assert_no_secret(_exception_texts(error))
    _assert_no_secret([str(error.description)])


def test_boundary_keeps_intentional_failure_and_base_exceptions(monkeypatch):
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)
    intended = Failure(description="safe", metadata={"run_id": 3}, allow_retries=False)

    @dagster_definitions._redact_op_errors
    def failing() -> None:
        raise intended

    with pytest.raises(Failure) as raised:
        failing()
    assert raised.value is intended

    @dagster_definitions._redact_op_errors
    def interrupted() -> None:
        raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        interrupted()


def test_boundary_still_redacts_when_settings_cannot_load(monkeypatch):
    def broken_settings() -> Settings:
        raise RuntimeError("settings unavailable")

    monkeypatch.setattr(dagster_definitions, "get_settings", broken_settings)

    @dagster_definitions._redact_op_errors
    def body() -> None:
        raise ConnectionError(f"GET /x?serviceKey={URL_ONLY_KEY}&a=1")

    with pytest.raises(Exception) as raised:
        body()
    assert URL_ONLY_KEY not in "\n".join(_exception_texts(raised.value))


# --- 리뷰 후속(MED·LOW2~7) ---------------------------------------------------------------------------


def _wrapped(error: BaseException):
    @dagster_definitions._redact_op_errors
    def body() -> None:
        raise error

    return body


def _raise_leaky_from_helper() -> None:
    raise _leaky_error()


def test_failure_metadata_keeps_safe_frames_and_chain_types(monkeypatch, capsys):
    """MED: traceback 위치(file:line func)와 사슬의 종류 이름은 남기고, 원문은 남기지 않는다."""
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)

    @dagster_definitions._redact_op_errors
    def body() -> None:
        _raise_leaky_from_helper()

    with pytest.raises(Failure) as raised:
        body()
    metadata = {key: str(value.value) for key, value in raised.value.metadata.items()}
    frames = metadata["frames"].splitlines()
    assert any(line.endswith(" _raise_leaky_from_helper") and "test_dagster_error_redaction.py:" in line
               for line in frames)
    assert any(line.endswith(" body") for line in frames)
    assert metadata["error_chain"].splitlines() == ["builtins.ConnectionError", "builtins.ValueError"]
    _assert_no_secret(list(metadata.values()))
    # 가린 전체 traceback은 run 컨테이너의 compute log(stderr)로만 간다.
    err = capsys.readouterr().err
    assert "Traceback (most recent call last)" in err
    assert "_raise_leaky_from_helper" in err
    assert "builtins.ValueError: upstream said" in err
    assert "serviceKey=<redacted>" in err
    _assert_no_secret([err])


class _UnprintableError(Exception):
    def __str__(self) -> str:  # sanitizer 자체가 실패하는 경우(예: httpx.ResponseNotRead)
        raise RuntimeError(f"cannot render {KEX_KEY}")


def test_sanitizer_failure_falls_back_without_chaining(monkeypatch, capsys):
    """LOW2: 가리는 단계가 실패해도 원래 예외를 사슬에 매달지 않는다."""
    import httpx
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)
    with pytest.raises(Failure) as raised:
        _wrapped(_UnprintableError())()
    assert raised.value.description == f"{__name__}._UnprintableError: <unavailable>"
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    _assert_no_secret(_exception_texts(raised.value) + [capsys.readouterr().err])

    request = httpx.Request("GET", f"https://apis.data.go.kr/x?serviceKey={URL_ONLY_KEY}")
    response = httpx.Response(500, request=request, stream=httpx.ByteStream(b"body"))
    error = httpx.HTTPStatusError(f"500 for {request.url}", request=request, response=response)
    with pytest.raises(Failure) as raised:
        _wrapped(error)()
    assert raised.value.description == "httpx.HTTPStatusError: <unavailable>"
    assert raised.value.__context__ is None and raised.value.__cause__ is None
    _assert_no_secret(_exception_texts(raised.value) + [capsys.readouterr().err])


def test_only_interrupts_pass_through_other_base_exceptions_are_redacted(monkeypatch):
    """LOW3: KeyboardInterrupt·SystemExit·DagsterExecutionInterruptedError만 그대로 둔다."""
    import asyncio

    from dagster import Failure
    from dagster._core.errors import DagsterExecutionInterruptedError

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)
    for passthrough in (KeyboardInterrupt(), SystemExit(1), DagsterExecutionInterruptedError()):
        with pytest.raises(type(passthrough)):
            _wrapped(passthrough)()
    for converted, type_name in (
        (asyncio.CancelledError(f"cancel {KEX_KEY}"), "asyncio.exceptions.CancelledError"),
        (BaseExceptionGroup(f"group {KEX_KEY}", [GeneratorExit()]), "builtins.BaseExceptionGroup"),
    ):
        with pytest.raises(Failure) as raised:
            _wrapped(converted)()
        assert raised.value.metadata["error_type"].value == type_name
        assert raised.value.__context__ is None
        _assert_no_secret(_exception_texts(raised.value) + [raised.value.description])


def test_settings_validation_error_does_not_echo_input():
    """LOW4: ValidationError가 env 값을 그대로 옮기지 않는다."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as raised:
        Settings(database_url="sqlite+aiosqlite://", scheduler_mode=f"leak-{KEX_KEY}")
    assert KEX_KEY not in str(raised.value)


def test_infrastructure_secrets_are_redacted(monkeypatch):
    """LOW5: DB 비밀번호·RustFS secret·관리자/export 토큰도 가린다."""
    from dagster import Failure

    db_password = "FAKEdbPass4321"
    secrets = {
        "rustfs_secret_access_key": "FAKErustfsSecret77",
        "transport_admin_write_token": "FAKEadminWriteToken88",
        "transport_service_export_token": "FAKEserviceExportToken99xxxxxxxxxxxx",
    }
    monkeypatch.setattr(dagster_definitions, "get_settings", lambda: Settings(
        database_url=f"postgresql+asyncpg://transport_user:{db_password}@db:5432/transport", **secrets))
    message = f"connect failed password={db_password} " + " ".join(secrets.values())
    with pytest.raises(Failure) as raised:
        _wrapped(RuntimeError(message))()
    description = raised.value.description
    for secret in (db_password, *secrets.values()):
        assert secret not in description
    assert "<redacted>" in description


def test_description_is_capped(monkeypatch):
    """LOW6: 응답 본문 같은 긴 문장은 잘라서 남긴다."""
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)
    with pytest.raises(Failure) as raised:
        _wrapped(RuntimeError("x" * 10000))()
    assert len(raised.value.description) <= 2000


ENCODED_KEY = "FAKE+enc/Key=="


@pytest.mark.parametrize(
    ("configured", "seen"),
    [
        (ENCODED_KEY, ENCODED_KEY),                       # 원문
        (ENCODED_KEY, "FAKE%2Benc%2FKey%3D%3D"),          # URL 인코딩
        (ENCODED_KEY, "FAKE%252Benc%252FKey%253D%253D"),  # 이중 인코딩
        ("FAKE%2Benc%2FKey%3D%3D", ENCODED_KEY),          # 인코딩형을 설정, 원문이 보임
        ("FAKE%2Benc%2FKey%3D%3D", "FAKE%252Benc%252FKey%253D%253D"),
    ],
)
def test_encoded_key_variants_are_redacted(monkeypatch, configured, seen):
    """LOW7: data.go.kr 키의 `+`·`/`·`=`가 인코딩·이중 인코딩된 형태도 가린다."""
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", lambda: Settings(
        database_url="sqlite+aiosqlite://", data_go_kr_service_key=configured))
    with pytest.raises(Failure) as raised:
        _wrapped(RuntimeError(f"GET /x?key={seen}&b=1 token {seen}"))()
    description = raised.value.description
    assert seen not in description
    assert "FAKE+enc" not in description and "FAKE%2Benc" not in description and "FAKE%252Benc" not in description


def _recurse(depth: int) -> None:
    if depth == 0:
        raise RuntimeError("bottom")
    _recurse(depth - 1)


def test_frames_are_capped_to_the_most_recent(monkeypatch):
    """깊은 재귀는 마지막 50개 frame만 남기고 생략 사실을 메타데이터에 적는다."""
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", _secret_settings)

    @dagster_definitions._redact_op_errors
    def body() -> None:
        _recurse(300)

    with pytest.raises(Failure) as raised:
        body()
    metadata = {key: str(value.value) for key, value in raised.value.metadata.items()}
    frames = metadata["frames"].splitlines()
    assert len(frames) == 50
    assert frames[-1].endswith(" _recurse")  # 가장 안쪽(raise 지점)이 남는다.
    assert int(metadata["frames_omitted"]) == 2 + 301 - 50  # wrapper + body + _recurse 301단


class Err_FAKEframeKey42(RuntimeError):
    pass


def frame_FAKEframeKey42() -> None:
    raise Err_FAKEframeKey42("in a frame whose name collides with a secret")


def test_frames_and_chain_strings_are_redacted(monkeypatch):
    from dagster import Failure

    monkeypatch.setattr(dagster_definitions, "get_settings", lambda: Settings(
        database_url="sqlite+aiosqlite://", kex_ex_api_key="FAKEframeKey42"))
    with pytest.raises(Failure) as raised:
        _wrapped_call(frame_FAKEframeKey42)()
    metadata = {key: str(value.value) for key, value in raised.value.metadata.items()}
    assert "FAKEframeKey42" not in metadata["frames"]
    assert "frame_<redacted>" in metadata["frames"]
    assert metadata["error_chain"] == f"{__name__}.Err_<redacted>"
    assert "FAKEframeKey42" not in metadata["error_type"] + raised.value.description


def _wrapped_call(target):
    @dagster_definitions._redact_op_errors
    def body() -> None:
        target()

    return body
