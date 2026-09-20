from app.core.config import Settings


def test_opinet_browser_timeout_default_waits_for_slow_public_page_updates() -> None:
    settings = Settings()

    assert settings.opinet_browser_timeout_ms == 60_000
