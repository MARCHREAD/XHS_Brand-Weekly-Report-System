from pathlib import Path

import pytest

from collector.config import ConfigurationError, Settings, parse_cookie_string


def test_cookie_parser_preserves_equals() -> None:
    assert parse_cookie_string("a1=abc; token=a=b=c") == {"a1": "abc", "token": "a=b=c"}


def test_cookie_file_requires_session_fields(tmp_path: Path) -> None:
    path = tmp_path / "cookie.txt"
    path.write_text("a1=one; webId=two", encoding="utf-8")
    settings = Settings(cookie_file=path)
    with pytest.raises(ConfigurationError, match="web_session"):
        settings.cookie_string()


def test_cookie_file_loads_valid_cookie(tmp_path: Path) -> None:
    path = tmp_path / "cookie.txt"
    path.write_text("a1=one; web_session=two; webId=three", encoding="utf-8")
    settings = Settings(cookie_file=path)
    assert parse_cookie_string(settings.cookie_string())["web_session"] == "two"


def test_cookie_pool_uses_unique_independent_sessions(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.delenv("XHS_COOKIE", raising=False)
    monkeypatch.setenv(
        "XHS_COOKIE_POOL",
        "a1=one; web_session=s1; webId=w1\na1=two; web_session=s2; webId=w2\n"
        "a1=one; web_session=s1; webId=w1",
    )
    settings = Settings(cookie_file=tmp_path / "missing", worker_count=10)
    assert len(settings.cookie_strings()) == 2


def test_pgy_cookie_file_is_independent_from_xhs_cookie(tmp_path: Path) -> None:
    xhs_path = tmp_path / "xhs.txt"
    pgy_path = tmp_path / "pgy.txt"
    xhs_path.write_text("a1=xhs; web_session=xhs-session; webId=xhs-web", encoding="utf-8")
    pgy_path.write_text("a1=pgy; solar.beaker.session.id=pgy-session", encoding="utf-8")
    settings = Settings(cookie_file=xhs_path, pgy_cookie_file=pgy_path)

    assert parse_cookie_string(settings.cookie_string())["a1"] == "xhs"
    assert parse_cookie_string(settings.pgy_cookie_string())["a1"] == "pgy"
    assert settings.pgy_cookie_configured() is True
