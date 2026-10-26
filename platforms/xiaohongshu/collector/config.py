from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
REQUIRED_COOKIE_NAMES = {"a1", "web_session", "webId"}


class ConfigurationError(RuntimeError):
    pass


def parse_cookie_string(value: str) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for block in value.split(";"):
        block = block.strip()
        if not block or "=" not in block:
            continue
        name, cookie_value = block.split("=", 1)
        if name.strip():
            cookies[name.strip()] = cookie_value.strip()
    return cookies


@dataclass(frozen=True, slots=True)
class Settings:
    cookie_file: Path
    cookie_pool_file: Path | None = None
    pgy_cookie_file: Path | None = None
    impersonate: str = "chrome146"
    min_delay_seconds: float = 1.0
    timeout_seconds: float = 20.0
    pgy_timeout_seconds: float = 20.0
    pgy_max_retries: int = 1
    pgy_retry_backoff_seconds: float = 1.0
    worker_count: int = 10
    gpt_concurrency: int = 3
    cache_enabled: bool = True
    cache_search_seconds: float = 120.0
    cache_homefeed_seconds: float = 30.0
    cache_note_seconds: float = 600.0
    cache_author_seconds: float = 1800.0
    cache_comments_seconds: float = 120.0
    cache_author_notes_seconds: float = 300.0
    job_retention_seconds: float = 3600.0
    session_check_seconds: float = 900.0
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    openai_model: str = "gpt-4o-mini"
    output_dir: Path = PROJECT_ROOT / "output"

    @classmethod
    def from_env(cls) -> "Settings":
        configured_cookie_file = os.getenv("XHS_COOKIE_FILE", "secrets/xhs_cookie.txt")
        cookie_path = Path(configured_cookie_file)
        if not cookie_path.is_absolute():
            cookie_path = PROJECT_ROOT / cookie_path
        configured_pool_file = os.getenv("XHS_COOKIE_POOL_FILE", "secrets/xhs_cookies.txt")
        pool_path = Path(configured_pool_file)
        if not pool_path.is_absolute():
            pool_path = PROJECT_ROOT / pool_path
        configured_pgy_cookie_file = os.getenv("XHS_PGY_COOKIE_FILE", "secrets/pgy_cookie.txt")
        pgy_cookie_path = Path(configured_pgy_cookie_file)
        if not pgy_cookie_path.is_absolute():
            pgy_cookie_path = PROJECT_ROOT / pgy_cookie_path
        return cls(
            cookie_file=cookie_path.resolve(),
            cookie_pool_file=pool_path.resolve(),
            pgy_cookie_file=pgy_cookie_path.resolve(),
            impersonate=os.getenv("XHS_IMPERSONATE", "chrome146"),
            min_delay_seconds=max(0.8, float(os.getenv("XHS_MIN_DELAY_SECONDS", "1.0"))),
            timeout_seconds=max(5.0, float(os.getenv("XHS_TIMEOUT_SECONDS", "20"))),
            pgy_timeout_seconds=max(10.0, float(os.getenv("XHS_PGY_TIMEOUT_SECONDS", "20"))),
            pgy_max_retries=min(5, max(0, int(os.getenv("XHS_PGY_MAX_RETRIES", "1")))),
            pgy_retry_backoff_seconds=max(
                0.0, float(os.getenv("XHS_PGY_RETRY_BACKOFF_SECONDS", "1.0"))
            ),
            worker_count=min(10, max(1, int(os.getenv("XHS_WORKER_COUNT", "10")))),
            gpt_concurrency=min(10, max(1, int(os.getenv("XHS_GPT_CONCURRENCY", "3")))),
            cache_enabled=os.getenv("XHS_CACHE_ENABLED", "true").lower() not in {"0", "false", "no"},
            cache_search_seconds=max(0.0, float(os.getenv("XHS_CACHE_SEARCH_SECONDS", "120"))),
            cache_homefeed_seconds=max(0.0, float(os.getenv("XHS_CACHE_HOMEFEED_SECONDS", "30"))),
            cache_note_seconds=max(0.0, float(os.getenv("XHS_CACHE_NOTE_SECONDS", "600"))),
            cache_author_seconds=max(0.0, float(os.getenv("XHS_CACHE_AUTHOR_SECONDS", "1800"))),
            cache_comments_seconds=max(0.0, float(os.getenv("XHS_CACHE_COMMENTS_SECONDS", "120"))),
            cache_author_notes_seconds=max(0.0, float(os.getenv("XHS_CACHE_AUTHOR_NOTES_SECONDS", "300"))),
            job_retention_seconds=max(60.0, float(os.getenv("XHS_JOB_RETENTION_SECONDS", "3600"))),
            session_check_seconds=max(60.0, float(os.getenv("XHS_SESSION_CHECK_SECONDS", "900"))),
            api_host=os.getenv("XHS_API_HOST", "127.0.0.1"),
            api_port=int(os.getenv("XHS_API_PORT", "8000")),
            openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )

    @staticmethod
    def _normalize_cookie(value: str) -> str:
        cookies = parse_cookie_string(value)
        missing = REQUIRED_COOKIE_NAMES - cookies.keys()
        if missing:
            raise ConfigurationError(f"XHS cookie is missing required fields: {sorted(missing)}")
        return "; ".join(f"{name}={cookie_value}" for name, cookie_value in cookies.items())

    def cookie_string(self) -> str:
        inline = os.getenv("XHS_COOKIE", "").strip()
        if inline:
            value = inline
        elif self.cookie_file.is_file():
            value = self.cookie_file.read_text(encoding="utf-8").strip()
        else:
            raise ConfigurationError(
                "Configure XHS_COOKIE or create the local cookie file declared by XHS_COOKIE_FILE."
            )
        return self._normalize_cookie(value)

    def cookie_strings(self) -> list[str]:
        inline_pool = os.getenv("XHS_COOKIE_POOL", "").strip()
        if inline_pool:
            candidates = inline_pool.splitlines()
        elif self.cookie_pool_file and self.cookie_pool_file.is_file():
            candidates = self.cookie_pool_file.read_text(encoding="utf-8").splitlines()
        else:
            candidates = [self.cookie_string()]
        normalized: list[str] = []
        seen: set[str] = set()
        for candidate in candidates:
            candidate = candidate.strip()
            if not candidate or candidate.startswith("#"):
                continue
            value = self._normalize_cookie(candidate)
            if value not in seen:
                seen.add(value)
                normalized.append(value)
        if not normalized:
            raise ConfigurationError("The XHS cookie pool contains no usable sessions.")
        return normalized[: self.worker_count]

    def cookie_pool_size(self) -> int:
        try:
            return len(self.cookie_strings())
        except ConfigurationError:
            return 0

    def cookie_configured(self) -> bool:
        return (
            bool(os.getenv("XHS_COOKIE", "").strip())
            or bool(os.getenv("XHS_COOKIE_POOL", "").strip())
            or self.cookie_file.is_file()
            or bool(self.cookie_pool_file and self.cookie_pool_file.is_file())
        )

    def pgy_cookie_string(self, fallback: str | None = None) -> str:
        inline = os.getenv("XHS_PGY_COOKIE", "").strip()
        if inline:
            value = inline
        elif self.pgy_cookie_file and self.pgy_cookie_file.is_file():
            value = self.pgy_cookie_file.read_text(encoding="utf-8").strip()
        elif fallback:
            value = fallback
        else:
            raise ConfigurationError(
                "Configure XHS_PGY_COOKIE or create the local cookie file declared by XHS_PGY_COOKIE_FILE."
            )
        cookies = parse_cookie_string(value)
        if not cookies.get("a1"):
            raise ConfigurationError("Pgy cookie is missing required field: a1")
        return "; ".join(f"{name}={cookie_value}" for name, cookie_value in cookies.items())

    def pgy_cookie_configured(self) -> bool:
        return bool(os.getenv("XHS_PGY_COOKIE", "").strip()) or bool(
            self.pgy_cookie_file and self.pgy_cookie_file.is_file()
        )

    @property
    def openai_configured(self) -> bool:
        return bool(os.getenv("OPENAI_API_KEY", "").strip())
