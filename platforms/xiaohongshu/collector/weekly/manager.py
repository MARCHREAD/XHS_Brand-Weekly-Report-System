from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from uuid import uuid4

from ..config import PROJECT_ROOT
from .store import Store, now


def default_config():
    return json.loads((PROJECT_ROOT / "weekly_config.json").read_text(encoding="utf-8"))


class Manager:
    def __init__(self, output: Path):
        self.root = output / "weekly"
        self.root.mkdir(parents=True, exist_ok=True)
        self.processes = {}

    def store(self, job_id):
        if len(job_id) != 32 or any(c not in "0123456789abcdef" for c in job_id):
            raise ValueError("Invalid report id")
        directory = self.root / job_id
        if not (directory / "collection.sqlite3").exists():
            raise FileNotFoundError(job_id)
        return Store(directory)

    def latest(self):
        entries = [Store(p.parent).summary() for p in self.root.glob("*/collection.sqlite3")]
        for entry in entries:
            for action, field, failure in [("collect", "status", "interrupted"), ("analyze", "analysis_status", "failed"), ("train", "analysis_status", "failed")]:
                process = self.processes.get((entry.get("job_id"), action))
                pid_field = "pid" if action == "collect" else "analysis_pid"
                active_states = {"running", "cooldown", "pause_requested"} if action == "collect" else {"running"}
                if process is not None and process.pid == entry.get(pid_field) and process.poll() is not None and entry.get(field) in active_states:
                    store = self.store(entry["job_id"])
                    store.meta(**{field: failure, "process_exit_code": process.returncode})
                    entry.update(store.summary())
        return sorted(entries, key=lambda r: r.get("created_at", ""), reverse=True)

    def create(self, config):
        if any(x.get("status") in {"running", "cooldown", "pause_requested"} for x in self.latest()):
            raise ValueError("A collection is already running; inspect or pause it first")
        job_id = uuid4().hex
        store = Store(self.root / job_id)
        store.meta(job_id=job_id, config=config, status="created", stage="created", created_at=now())
        self.launch(job_id, "collect")
        return store.summary()

    def launch(self, job_id, action):
        store = self.store(job_id)
        if store.meta().get("status") in {"running", "cooldown", "pause_requested"} and action == "collect":
            raise ValueError("This report is already running")
        log = (store.directory / f"{action}.log").open("a", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONUTF8"] = "1"
        python = PROJECT_ROOT / ".venv-weekly" / "Scripts" / "python.exe"
        executable = str(python) if action != "collect" and python.exists() else sys.executable
        try:
            process = subprocess.Popen([executable, str(PROJECT_ROOT / "weekly.py"), action, "--job", job_id], cwd=PROJECT_ROOT, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        finally:
            log.close()
        self.processes[(job_id, action)] = process
        if action == "collect":
            store.meta(status="running", pid=process.pid)
        else:
            store.meta(analysis_status="running", analysis_pid=process.pid)
        return store.summary()
