"""SQLite storage for devices, usage and cached Riot data.

미니 PC 한 대에서 돌리는 동안은 SQLite로 충분하다. 클라우드로 옮겨 여러 대로 늘릴 때 이 파일만 PostgreSQL로 바꾼다.
요청마다 새 연결을 열어 스레드 문제를 피하고, WAL 모드로 읽기와 쓰기가 서로 막지 않게 한다.
"""
import json
import sqlite3
from contextlib import closing
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    token_hash TEXT NOT NULL UNIQUE,
    created_at REAL NOT NULL,
    last_seen_at REAL NOT NULL,
    app_version TEXT
);
CREATE TABLE IF NOT EXISTS usage_daily (
    device_id INTEGER NOT NULL,
    day TEXT NOT NULL,
    riot_requests INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (device_id, day)
);
CREATE TABLE IF NOT EXISTS riot_accounts (
    name_key TEXT PRIMARY KEY,
    puuid TEXT NOT NULL,
    data TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS league_entries (
    puuid TEXT PRIMARY KEY,
    data TEXT,
    fetched_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS player_match_lists (
    puuid TEXT NOT NULL,
    count INTEGER NOT NULL,
    match_ids TEXT NOT NULL,
    fetched_at REAL NOT NULL,
    PRIMARY KEY (puuid, count)
);
CREATE TABLE IF NOT EXISTS matches (
    match_id TEXT PRIMARY KEY,
    game_start INTEGER,
    game_mode TEXT,
    detail TEXT NOT NULL,
    fetched_at REAL NOT NULL
);
"""


class Database:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self.connect()) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(SCHEMA)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        return db

    def one(self, sql, params=()):
        with closing(self.connect()) as db:
            return db.execute(sql, params).fetchone()

    def run(self, sql, params=()):
        with closing(self.connect()) as db, db:
            return db.execute(sql, params)

    # --- devices / usage
    def add_device(self, token_hash, now, app_version):
        with closing(self.connect()) as db, db:
            return db.execute("INSERT INTO devices (token_hash, created_at, last_seen_at, app_version) VALUES (?, ?, ?, ?)",
                              (token_hash, now, now, app_version)).lastrowid

    def find_device(self, token_hash):
        row = self.one("SELECT id FROM devices WHERE token_hash=?", (token_hash,))
        return row["id"] if row else None

    def touch_device(self, device_id, now, app_version):
        self.run("UPDATE devices SET last_seen_at=?, app_version=? WHERE id=?", (now, app_version, device_id))

    def count_request(self, device_id, day):
        """오늘 요청 수를 1 늘리고 늘어난 값을 돌려준다."""
        with closing(self.connect()) as db, db:
            db.execute("""INSERT INTO usage_daily (device_id, day, riot_requests) VALUES (?, ?, 1)
                          ON CONFLICT(device_id, day) DO UPDATE SET riot_requests = riot_requests + 1""",
                       (device_id, day))
            return db.execute("SELECT riot_requests FROM usage_daily WHERE device_id=? AND day=?",
                              (device_id, day)).fetchone()[0]

    # --- cached Riot data
    def cached_json(self, table, key_column, key, column, max_age, now, extra=""):
        row = self.one(f"SELECT {column} AS value, fetched_at FROM {table} WHERE {key_column}=? {extra}", (key,))
        if row is None or (max_age is not None and now - row["fetched_at"] > max_age):
            return None, False
        return (json.loads(row["value"]) if row["value"] is not None else None), True

    def save_account(self, name_key, data, now):
        self.run("INSERT OR REPLACE INTO riot_accounts VALUES (?, ?, ?, ?)",
                 (name_key, data["puuid"], json.dumps(data, ensure_ascii=False), now))

    def save_league(self, puuid, data, now):
        self.run("INSERT OR REPLACE INTO league_entries VALUES (?, ?, ?)",
                 (puuid, json.dumps(data) if data is not None else None, now))

    def match_list(self, puuid, count, max_age, now):
        row = self.one("SELECT match_ids, fetched_at FROM player_match_lists WHERE puuid=? AND count=?", (puuid, count))
        if row is None or now - row["fetched_at"] > max_age:
            return None
        return json.loads(row["match_ids"])

    def save_match_list(self, puuid, count, match_ids, now):
        self.run("INSERT OR REPLACE INTO player_match_lists VALUES (?, ?, ?, ?)",
                 (puuid, count, json.dumps(match_ids), now))

    def match(self, match_id):
        row = self.one("SELECT detail FROM matches WHERE match_id=?", (match_id,))
        return json.loads(row["detail"]) if row else None

    def save_match(self, match_id, detail, now):
        info = detail.get("info") or {}
        self.run("INSERT OR REPLACE INTO matches VALUES (?, ?, ?, ?, ?)",
                 (match_id, info.get("gameStartTimestamp"), info.get("gameMode"),
                  json.dumps(detail, ensure_ascii=False), now))
