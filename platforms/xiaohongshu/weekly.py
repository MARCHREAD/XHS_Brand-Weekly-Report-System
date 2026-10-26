"""Run/resume weekly collection or models. No arguments creates the configured report."""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import replace
import json

from collector.config import Settings
from collector.weekly.collection import Adapter, Collector
from collector.weekly.manager import Manager, default_config


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["collect", "analyze", "train"], nargs="?", default="collect")
    parser.add_argument("--job")
    args = parser.parse_args()
    settings = Settings.from_env()
    manager = Manager(settings.output_dir)
    if not args.job:
        # Creates a persistent child process using the same platform runtime.
        print(json.dumps(manager.create(default_config()), ensure_ascii=False))
        return
    store = manager.store(args.job)
    if args.action == "collect":
        from collector.service import CollectorService
        settings = replace(settings, worker_count=1, cache_enabled=False, min_delay_seconds=max(1.5, settings.min_delay_seconds))
        if not settings.cookie_configured():
            store.meta(status="login_required", error="Open the workbench Cookie login")
            return
        service = CollectorService(settings)
        asyncio.run(Collector(store, Adapter(service)).run())
        print(json.dumps(store.summary(), ensure_ascii=False))
        if store.meta().get("status") in {"completed", "partial"} and store.meta().get("analysis_status") != "running":
            manager.launch(args.job, "analyze")
    else:
        from collector.weekly.analysis import analyze, train_sentiment
        try:
            if args.action == "train":
                train_sentiment(store)
            analyze(store)
        except Exception as exc:
            store.meta(analysis_status="failed", analysis_error=f"{type(exc).__name__}: {str(exc)[:300]}")
            raise


if __name__ == "__main__":
    main()
