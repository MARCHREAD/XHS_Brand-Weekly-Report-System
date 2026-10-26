from __future__ import annotations


class XhsCollectorError(RuntimeError):
    """Base error returned by the collector."""


class XhsUpstreamError(XhsCollectorError):
    def __init__(
        self,
        message: str,
        *,
        status_code: int = 502,
        upstream_status: int | None = None,
        upstream_code: int | str | None = None,
        auth_failure: bool = False,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.upstream_status = upstream_status
        self.upstream_code = upstream_code
        self.auth_failure = auth_failure


class EnrichmentError(XhsCollectorError):
    pass
