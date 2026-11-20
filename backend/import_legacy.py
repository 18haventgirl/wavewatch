"""Read a consistent SQLite v5 snapshot; atomically import into an EMPTY V2 DB."""
import hashlib
import json
from pathlib import Path
import shutil
import sqlite3
import time
from contextlib import closing
from sqlalchemy import select, func, insert, text
from backend.storage import tables as t

LEGACY_TABLES = ['countries', 'publishers', 'data_scopes', 'categories', 'sources',
                 'articles', 'article_sources', 'source_entries', 'article_attachments',
                 'versions', 'events', 'runs', 'crawl_pages', 'metadata', 'file_checks',
                 'file_blobs', 'file_versions']


def read_snapshot(path):
    path = Path(path).resolve(strict=True)
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True)) as source:
        source.row_factory = sqlite3.Row
        source.execute('BEGIN')
        if source.execute('PRAGMA user_version').fetchone()[0] != 5:
            raise ValueError('Only a validated SQLite v5 snapshot can be imported')
        if source.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('Source database has broken relationships')
        snapshot = {name: [dict(r) for r in source.execute('SELECT * FROM "' + name + '"')]
                    for name in LEGACY_TABLES}
    for row in snapshot['sources']:
        row['config'] = json.loads(row['config'])
    for row in snapshot['runs']:
        row['details'] = json.loads(row['details']) if row.get('details') else None
    for row in snapshot['articles']:
        description = row.get('description', '')
        row['subtitle'] = '' if description.startswith('列表标题不可读') else description
        row['description'] = ''
    # Preserve all relationships and insert roots before children, regardless of old row order.
    ordered, pending, known = [], list(snapshot['categories']), set()
    while pending:
        ready = [r for r in pending if r['parent_id'] is None or r['parent_id'] in known]
        if not ready:
            raise ValueError('Category tree has a cycle or missing parent')
        for row in ready:
            ordered.append(row)
            known.add(row['id'])
            pending.remove(row)
    snapshot['categories'] = ordered
    return snapshot


def fingerprint(rows):
    normalized = sorted(json.dumps(r, sort_keys=True, ensure_ascii=False, separators=(',', ':')) for r in rows)
    return hashlib.sha256('\n'.join(normalized).encode()).hexdigest()


def import_snapshot(engine, path, owner='legacy-owner', apply=False, target_files=None):
    snapshot = read_snapshot(path)
    source_root = Path(path).resolve().parent / 'attachments'
    # Original Windows absolute paths are never trusted on the server.
    for row in snapshot['file_blobs']:
        file = source_root / row['digest']
        if not file.is_file() or file.stat().st_size != row['bytes'] or hashlib.sha256(file.read_bytes()).hexdigest() != row['digest']:
            raise ValueError('Missing or damaged attachment: ' + row['digest'])
        row['path'] = 'attachments/' + row['digest']
    counts = {name: len(rows) for name, rows in snapshot.items()}
    if not apply:
        return {'mode': 'dry-run', 'counts': counts, 'attachments_verified': counts['file_blobs']}
    if snapshot['file_blobs'] and target_files is None:
        raise ValueError('Set --target-files so attachment copies accompany the import')
    with engine.begin() as conn:
        if conn.dialect.name == 'postgresql':
            if not conn.scalar(text('SELECT pg_try_advisory_xact_lock(673861012)')):
                raise ValueError('Another import is running')
        # Do not mix a seeded/testing DB with a migration snapshot.
        if any(conn.scalar(select(func.count()).select_from(table)) for table in t.values()):
            raise ValueError('Target database must be empty; existing data was not overwritten')
        for name in LEGACY_TABLES:
            for row in snapshot[name]:
                conn.execute(insert(t[name]).values(**row))
        conn.execute(insert(t['users']).values(id=owner, name='原本机拥有者', role='admin', active=1, created=time.time()))
        for row in snapshot['events']:
            if row['unread'] == 0:
                conn.execute(insert(t['user_event_states']).values(user_id=owner, event_id=row['id'], read_at=time.time()))
        for name in LEGACY_TABLES:
            imported = [dict(r) for r in conn.execute(select(t[name])).mappings()]
            if fingerprint(imported) != fingerprint(snapshot[name]):
                raise ValueError('Import verification failed: ' + name)
        if conn.dialect.name == 'postgresql':
            # Explicit legacy integer IDs must not leave sequences at their initial value.
            for name in ['versions', 'runs', 'crawl_pages']:
                conn.execute(text("SELECT setval(pg_get_serial_sequence(:name, 'id'), "
                                  'COALESCE((SELECT MAX(id) FROM "' + name + '"), 1), '
                                  'EXISTS(SELECT 1 FROM "' + name + '"))'), {'name': name})
        # Copy immutable blobs before committing references. Failed imports may leave
        # unreferenced blobs, but never commit references to an absent file.
        for row in snapshot['file_blobs']:
            target = Path(target_files).resolve() / row['path']
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if hashlib.sha256(target.read_bytes()).hexdigest() != row['digest']:
                    raise ValueError('Destination attachment conflict')
            else:
                temporary = target.with_suffix('.importing')
                shutil.copyfile(source_root / row['digest'], temporary)
                if hashlib.sha256(temporary.read_bytes()).hexdigest() != row['digest']:
                    raise ValueError('Attachment copy verification failed')
                temporary.replace(target)
    return {'mode': 'imported', 'counts': counts, 'owner': owner, 'verified': True}
