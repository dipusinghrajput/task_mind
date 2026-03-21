"""
Database layer — SQLite with multi-user schema.
On Render: uses /data/planner.db (persistent disk).
Locally:   uses ./planner.db
"""

import sqlite3, os
from flask import g

_default = "/data/planner.db" if os.path.isdir("/data") else "planner.db"
DB_PATH = os.environ.get("PLANNER_DB", _default)

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys=ON")
        g.db.execute("PRAGMA journal_mode=WAL")
    return g.db

def close_db():
    db = g.pop("db", None)
    if db:
        db.close()

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,
    email       TEXT DEFAULT '',
    pin         TEXT DEFAULT '0000',
    timezone    TEXT DEFAULT 'Asia/Kolkata',
    day_start   TEXT DEFAULT '06:00',
    day_end     TEXT DEFAULT '23:00',
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER UNIQUE REFERENCES users(id) ON DELETE CASCADE,
    subscription TEXT NOT NULL,
    user_agent   TEXT DEFAULT '',
    updated_at   TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS categories (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    name    TEXT NOT NULL,
    color   TEXT DEFAULT '#6c63ff',
    icon    TEXT DEFAULT '📌'
);

CREATE TABLE IF NOT EXISTS tasks (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id             INTEGER REFERENCES users(id) ON DELETE CASCADE,
    category_id         INTEGER REFERENCES categories(id),
    title               TEXT NOT NULL,
    description         TEXT,
    duration_min        INTEGER NOT NULL DEFAULT 60,
    remaining_duration  INTEGER,
    deadline            TEXT,
    priority            INTEGER DEFAULT 2,
    preferred_time      TEXT,
    status              TEXT DEFAULT 'todo',
    is_recurring        INTEGER DEFAULT 0,
    recur_pattern       TEXT,
    created_at          TEXT DEFAULT (datetime('now')),
    completed_at        TEXT,
    notes               TEXT
);

CREATE TABLE IF NOT EXISTS routines (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title        TEXT NOT NULL,
    start_time   TEXT NOT NULL,
    duration_min INTEGER NOT NULL,
    repeat_days  TEXT,
    on_holiday   INTEGER DEFAULT 0,
    color        TEXT DEFAULT '#06b6d4',
    is_active    INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS fixed_schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    title       TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    repeat_days TEXT DEFAULT 'monday,tuesday,wednesday,thursday,friday',
    is_editable INTEGER DEFAULT 1,
    is_active   INTEGER DEFAULT 1,
    color       TEXT DEFAULT '#94a3b8',
    category    TEXT DEFAULT 'fixed'
);

CREATE TABLE IF NOT EXISTS slot_overrides (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    fixed_id   INTEGER REFERENCES fixed_schedule(id) ON DELETE CASCADE,
    date       TEXT NOT NULL,
    free_start TEXT NOT NULL,
    free_end   TEXT NOT NULL,
    label      TEXT DEFAULT 'Free Period'
);

CREATE TABLE IF NOT EXISTS holidays (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
    date    TEXT NOT NULL,
    label   TEXT DEFAULT 'Holiday',
    UNIQUE(user_id, date)
);

CREATE TABLE IF NOT EXISTS schedule (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER REFERENCES users(id) ON DELETE CASCADE,
    task_id     INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    date        TEXT NOT NULL,
    title       TEXT NOT NULL,
    start_time  TEXT NOT NULL,
    end_time    TEXT NOT NULL,
    block_type  TEXT DEFAULT 'task',
    category    TEXT DEFAULT 'general',
    color       TEXT DEFAULT '#6c63ff',
    is_split    INTEGER DEFAULT 0,
    split_part  INTEGER DEFAULT 1,
    split_total INTEGER DEFAULT 1,
    status      TEXT DEFAULT 'pending',
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_logs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
    task_id         INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    schedule_id     INTEGER REFERENCES schedule(id) ON DELETE SET NULL,
    start_time      TEXT NOT NULL,
    end_time        TEXT,
    actual_duration INTEGER,
    action          TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
    type         TEXT NOT NULL,
    title        TEXT NOT NULL,
    message      TEXT NOT NULL,
    scheduled_at TEXT NOT NULL,
    sent         INTEGER DEFAULT 0,
    sent_at      TEXT,
    data         TEXT
);

CREATE INDEX IF NOT EXISTS idx_tasks_user   ON tasks(user_id, status);
CREATE INDEX IF NOT EXISTS idx_sched_date   ON schedule(user_id, date);
CREATE INDEX IF NOT EXISTS idx_notif_user   ON notifications(user_id, sent, scheduled_at);
"""

def init_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True) if os.path.dirname(DB_PATH) else None
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.commit()
    conn.close()
    print(f"[DB] Ready: {DB_PATH}")

if __name__ == "__main__":
    init_db()
