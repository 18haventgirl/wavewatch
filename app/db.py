"""SQLite storage: connection handling, schema and column seeding.

One database file (data/guanlan.sqlite3).  The previous engine-based database
(data/observatory.sqlite3) is never modified; it is imported once by
app.legacy when the new database is first created.
"""
from __future__ import annotations

import contextlib
import json
import sqlite3
import time
from typing import Any, Iterator

from . import config

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS sources(
  id            TEXT PRIMARY KEY,
  name          TEXT NOT NULL,
  grp           TEXT NOT NULL,
  role          TEXT NOT NULL CHECK(role IN ('core','news')),
  column_id     INTEGER NOT NULL,
  position      INTEGER NOT NULL DEFAULT 0,
  configured    INTEGER NOT NULL DEFAULT 1,
  enabled       INTEGER NOT NULL DEFAULT 1,
  list_minutes  INTEGER NOT NULL,
  article_hours INTEGER NOT NULL,
  notify        TEXT NOT NULL CHECK(notify IN ('instant','digest','off')),
  state         TEXT NOT NULL DEFAULT 'idle',
  error         TEXT NOT NULL DEFAULT '',
  fail_count    INTEGER NOT NULL DEFAULT 0,
  initialized   INTEGER NOT NULL DEFAULT 0,
  reported_total INTEGER,
  last_check    REAL,
  last_success  REAL,
  last_full     REAL,
  next_check    REAL NOT NULL DEFAULT 0,
  full_requested INTEGER NOT NULL DEFAULT 0,
  alerted_at    REAL
);

CREATE TABLE IF NOT EXISTS articles(
  id            TEXT PRIMARY KEY,
  url           TEXT NOT NULL UNIQUE,
  kind          TEXT NOT NULL CHECK(kind IN ('article','attachment')),
  title         TEXT NOT NULL,
  subtitle      TEXT NOT NULL DEFAULT '',
  origin        TEXT NOT NULL DEFAULT '',
  published     TEXT,
  discovered    REAL NOT NULL,
  title_ok      INTEGER NOT NULL DEFAULT 1,
  last_check    REAL,
  next_check    REAL NOT NULL DEFAULT 0,
  check_error   TEXT NOT NULL DEFAULT '',
  fail_count    INTEGER NOT NULL DEFAULT 0,
  rebase        INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS articles_due ON articles(next_check);
CREATE INDEX IF NOT EXISTS articles_published ON articles(published);

-- One row per official list entry.  Two entries may point to the same article.
CREATE TABLE IF NOT EXISTS entries(
  source_id    TEXT NOT NULL REFERENCES sources(id),
  external_key TEXT NOT NULL,
  article_id   TEXT NOT NULL REFERENCES articles(id),
  page         INTEGER,
  position     INTEGER,
  raw_title    TEXT NOT NULL DEFAULT '',
  first_seen   REAL NOT NULL,
  last_seen    REAL NOT NULL,
  PRIMARY KEY(source_id, external_key)
);
CREATE INDEX IF NOT EXISTS entries_article ON entries(article_id, source_id);
CREATE INDEX IF NOT EXISTS entries_order ON entries(source_id, position);

-- Attachment files linked from article pages; one file may serve several articles.
CREATE TABLE IF NOT EXISTS links(
  parent_id     TEXT NOT NULL REFERENCES articles(id),
  attachment_id TEXT NOT NULL REFERENCES articles(id),
  first_seen    REAL NOT NULL,
  PRIMARY KEY(parent_id, attachment_id),
  CHECK(parent_id != attachment_id)
);
CREATE INDEX IF NOT EXISTS links_child ON links(attachment_id);

CREATE TABLE IF NOT EXISTS files(
  digest       TEXT PRIMARY KEY,
  bytes        INTEGER NOT NULL,
  content_type TEXT NOT NULL DEFAULT '',
  created      REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS versions(
  id          INTEGER PRIMARY KEY,
  article_id  TEXT NOT NULL REFERENCES articles(id),
  created     REAL NOT NULL,
  digest      TEXT NOT NULL,
  content     TEXT NOT NULL,
  file_digest TEXT REFERENCES files(digest),
  baseline    INTEGER NOT NULL DEFAULT 0,
  note        TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS versions_article ON versions(article_id, id);

-- Immutable facts about what changed.  article_id is always the article a reader
-- opens; attachment_id is set when the change concerns one of its files.
CREATE TABLE IF NOT EXISTS events(
  id            INTEGER PRIMARY KEY,
  article_id    TEXT NOT NULL REFERENCES articles(id),
  attachment_id TEXT REFERENCES articles(id),
  version_id    INTEGER REFERENCES versions(id),
  kind          TEXT NOT NULL CHECK(kind IN ('new','changed','attachment_new','attachment_changed')),
  created       REAL NOT NULL,
  summary       TEXT NOT NULL DEFAULT '',
  read_at       REAL,
  route         TEXT NOT NULL DEFAULT 'pending',
  email_id      INTEGER REFERENCES emails(id)
);
CREATE UNIQUE INDEX IF NOT EXISTS events_unique ON events(article_id, IFNULL(attachment_id,''), kind, IFNULL(version_id,0));
CREATE INDEX IF NOT EXISTS events_created ON events(created);
CREATE INDEX IF NOT EXISTS events_route ON events(route);

CREATE TABLE IF NOT EXISTS runs(
  id        INTEGER PRIMARY KEY,
  source_id TEXT NOT NULL REFERENCES sources(id),
  mode      TEXT NOT NULL CHECK(mode IN ('quick','full')),
  started   REAL NOT NULL,
  finished  REAL,
  state     TEXT NOT NULL CHECK(state IN ('running','ok','error','interrupted')),
  pages     INTEGER NOT NULL DEFAULT 0,
  rows      INTEGER NOT NULL DEFAULT 0,
  added     INTEGER NOT NULL DEFAULT 0,
  message   TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS runs_source ON runs(source_id, id);

CREATE TABLE IF NOT EXISTS emails(
  id           INTEGER PRIMARY KEY,
  kind         TEXT NOT NULL CHECK(kind IN ('instant','digest','alert','test')),
  subject      TEXT NOT NULL,
  text_body    TEXT NOT NULL,
  html_body    TEXT NOT NULL,
  recipients   TEXT NOT NULL,
  created      REAL NOT NULL,
  state        TEXT NOT NULL CHECK(state IN ('pending','sent','failed')),
  attempts     INTEGER NOT NULL DEFAULT 0,
  next_attempt REAL NOT NULL DEFAULT 0,
  last_error   TEXT NOT NULL DEFAULT '',
  sent_at      REAL
);
CREATE INDEX IF NOT EXISTS emails_due ON emails(state, next_attempt);

CREATE TABLE IF NOT EXISTS settings(
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
"""


def connect() -> sqlite3.Connection:
    config.DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


@contextlib.contextmanager
def tx() -> Iterator[sqlite3.Connection]:
    """One short transaction.  Never hold one open across network requests."""
    conn = connect()
    try:
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def rows(conn: sqlite3.Connection, sql: str, args: Any = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, args).fetchall()]


def row(conn: sqlite3.Connection, sql: str, args: Any = ()) -> dict | None:
    found = conn.execute(sql, args).fetchone()
    return dict(found) if found else None


# --- settings ---------------------------------------------------------------

def get_setting(conn: sqlite3.Connection, key: str, default: Any = None) -> Any:
    found = conn.execute('SELECT value FROM settings WHERE key=?', (key,)).fetchone()
    return json.loads(found['value']) if found else default


def set_setting(conn: sqlite3.Connection, key: str, value: Any) -> None:
    conn.execute('INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',
                 (key, json.dumps(value, ensure_ascii=False)))


# --- startup ------------------------------------------------------------------

def seed_sources(conn: sqlite3.Connection) -> None:
    """Sync the configured columns; user-tuned values (interval, notify) are kept."""
    configured = config.load_sources()
    ids = [s['id'] for s in configured]
    for position, s in enumerate(configured):
        conn.execute(
            '''INSERT INTO sources(id,name,grp,role,column_id,position,configured,list_minutes,article_hours,notify)
               VALUES(?,?,?,?,?,?,1,?,?,?)
               ON CONFLICT(id) DO UPDATE SET name=excluded.name, grp=excluded.grp, role=excluded.role,
                 column_id=excluded.column_id, position=excluded.position, configured=1''',
            (s['id'], s['name'], s['group'], s['role'], s['column_id'], position,
             config.DEFAULT_LIST_MINUTES, config.DEFAULT_ARTICLE_HOURS[s['role']], config.DEFAULT_NOTIFY[s['role']]))
    conn.execute(f"UPDATE sources SET configured=0 WHERE id NOT IN ({','.join('?' * len(ids))})", ids)


def init() -> bool:
    """Create or upgrade the database.  Returns True when it was newly created."""
    fresh = not config.DB_PATH.exists()
    conn = connect()
    try:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript(SCHEMA)
        version = conn.execute('PRAGMA user_version').fetchone()[0]
        if version > SCHEMA_VERSION:
            raise RuntimeError(f'数据库结构版本 {version} 比程序新，请使用对应版本的程序')
        conn.execute(f'PRAGMA user_version={SCHEMA_VERSION}')
        seed_sources(conn)
        now = time.time()
        conn.execute("UPDATE runs SET state='interrupted', finished=?, message='程序在检查过程中退出' WHERE state='running'", (now,))
        conn.execute("UPDATE sources SET state=CASE WHEN error!='' THEN 'error' ELSE 'idle' END WHERE state='checking'")
        if conn.execute('PRAGMA foreign_key_check').fetchall():
            raise RuntimeError('数据库关系校验失败')
        conn.commit()
    finally:
        conn.close()
    return fresh
