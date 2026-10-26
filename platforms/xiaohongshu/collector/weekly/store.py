from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Store:
    """One local database per report; credentials never leave this directory."""

    def __init__(self, directory: Path):
        self.directory = directory
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "collection.sqlite3"
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("CREATE TABLE IF NOT EXISTS records(kind TEXT, key TEXT, data TEXT NOT NULL, PRIMARY KEY(kind,key))")

    def connect(self):
        return sqlite3.connect(self.path, timeout=30)

    def get(self, kind, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT data FROM records WHERE kind=? AND key=?", (kind, key)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, kind, key, data):
        self.put_many([(kind, key, data)])

    def put_many(self, records):
        with self.connect() as db:
            db.executemany("INSERT OR REPLACE INTO records VALUES(?,?,?)", [(k, key, json.dumps(v, ensure_ascii=False)) for k, key, v in records])

    def items(self, kind):
        with self.connect() as db:
            rows = db.execute("SELECT key,data FROM records WHERE kind=? ORDER BY key", (kind,)).fetchall()
        return [(key, json.loads(data)) for key, data in rows]

    def count(self, kind):
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM records WHERE kind=?", (kind,)).fetchone()[0]

    def meta(self, **changes):
        meta = self.get("meta", "job", {})
        if changes:
            meta.update(changes, updated_at=now())
            self.put("meta", "job", meta)
        return meta

    def summary(self):
        meta = self.meta()
        searches = [{k: value for k, value in v.items() if k not in {"search_id", "seen_pages"}} for _, v in self.items("search")]
        with self.connect() as db:
            completed = db.execute("SELECT COUNT(*) FROM records WHERE kind='note' AND json_extract(data,'$.complete')=1").fetchone()[0]
            pending = db.execute("SELECT COUNT(*) FROM records WHERE kind='note' AND COALESCE(json_extract(data,'$.complete'),0)=0").fetchone()[0]
        return {**meta, "searches": searches, "notes": self.count("note"), "comments": self.count("comment"), "notes_complete": completed, "notes_incomplete": pending}


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)
