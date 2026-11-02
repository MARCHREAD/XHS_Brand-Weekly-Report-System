from __future__ import annotations

import uvicorn

from collector.config import Settings


def main() -> None:
    settings = Settings.from_env()
    uvicorn.run(
        "collector.api:app",
        host=settings.api_host,
        port=settings.api_port,
        reload=False,
        access_log=False,
    )


if __name__ == "__main__":
    main()
