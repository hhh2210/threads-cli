import json
import os
import sqlite3
import uuid
from pathlib import Path

from .models import Post, now_iso


def data_dir() -> Path:
    return Path(os.environ.get("THREADS_CLI_HOME", "~/.local/share/threads-cli")).expanduser()


def private_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.chmod(0o700)
    return path


class Store:
    def __init__(self, directory: Path | None = None):
        self.directory = private_dir(directory or data_dir())
        db = self.directory / "evidence.sqlite3"
        self.db = sqlite3.connect(db)
        db.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS posts (
                code TEXT PRIMARY KEY, username TEXT NOT NULL,
                created_at TEXT, collected_at TEXT NOT NULL, payload TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY, started_at TEXT NOT NULL, kind TEXT NOT NULL,
                query TEXT NOT NULL, finished_at TEXT, metadata TEXT
            );
            CREATE TABLE IF NOT EXISTS observations (
                run_id TEXT NOT NULL, code TEXT NOT NULL,
                PRIMARY KEY(run_id, code)
            );
            CREATE TABLE IF NOT EXISTS annotations (
                username TEXT PRIMARY KEY, region TEXT, evidence_url TEXT,
                note TEXT, contacted_at TEXT, contact_evidence_url TEXT
            );
        """)
        if "contact_evidence_url" not in {
            row[1] for row in self.db.execute("PRAGMA table_info(annotations)")
        }:
            self.db.execute("ALTER TABLE annotations ADD COLUMN contact_evidence_url TEXT")
        self.db.commit()

    def close(self):
        self.db.close()

    def start_run(self, kind: str, query: str) -> str:
        run_id = uuid.uuid4().hex[:12]
        self.db.execute(
            "INSERT INTO runs(id,started_at,kind,query) VALUES(?,?,?,?)",
            (run_id, now_iso(), kind, query),
        )
        self.db.commit()
        return run_id

    def save(self, posts: list[Post], run_id: str):
        for post in posts:
            old = self.get(post.code)
            payload = post.to_dict()
            if old:
                # Different page projections omit counts/context. Missing is not zero.
                for key, value in old.items():
                    if payload.get(key) is None and value is not None:
                        payload[key] = value
                if not payload["text"] and old.get("text"):
                    payload["text"] = old["text"]
            self.db.execute(
                "INSERT INTO posts VALUES(?,?,?,?,?) ON CONFLICT(code) DO UPDATE SET "
                "username=excluded.username,created_at=excluded.created_at,"
                "collected_at=excluded.collected_at,payload=excluded.payload",
                (
                    post.code,
                    post.username,
                    payload["created_at"],
                    post.collected_at,
                    json.dumps(payload, ensure_ascii=False),
                ),
            )
            self.db.execute("INSERT OR IGNORE INTO observations VALUES(?,?)", (run_id, post.code))
        self.db.commit()

    def finish_run(self, run_id: str, metadata: dict):
        self.db.execute(
            "UPDATE runs SET finished_at=?,metadata=? WHERE id=?",
            (now_iso(), json.dumps(metadata, ensure_ascii=False), run_id),
        )
        self.db.commit()

    def get(self, code: str) -> dict | None:
        row = self.db.execute("SELECT payload FROM posts WHERE code=?", (code,)).fetchone()
        return json.loads(row[0]) if row else None

    def all_posts(self, run_id: str | None = None) -> list[dict]:
        if run_id:
            rows = self.db.execute(
                "SELECT p.payload FROM posts p JOIN observations o ON p.code=o.code "
                "WHERE o.run_id=? ORDER BY p.created_at DESC",
                (run_id,),
            )
        else:
            rows = self.db.execute("SELECT payload FROM posts ORDER BY created_at DESC")
        return [json.loads(row[0]) for row in rows]

    def annotations(self) -> dict:
        return {row["username"]: dict(row) for row in self.db.execute("SELECT * FROM annotations")}

    def annotate(self, username: str, **fields):
        valid = {"region", "evidence_url", "note", "contacted_at", "contact_evidence_url"}
        if set(fields) - valid:
            raise ValueError("Unknown annotation field")
        self.db.execute("INSERT OR IGNORE INTO annotations(username) VALUES(?)", (username,))
        for key, value in fields.items():
            self.db.execute(f"UPDATE annotations SET {key}=? WHERE username=?", (value, username))
        self.db.commit()

    def runs(self, limit: int = 10) -> list[dict]:
        rows = self.db.execute("SELECT * FROM runs ORDER BY started_at DESC LIMIT ?", (limit,))
        result = []
        for row in rows:
            value = dict(row)
            value["metadata"] = json.loads(value["metadata"]) if value["metadata"] else None
            result.append(value)
        return result
