"""One-time import from the previous changedetection.io based version (schema v5).

The old database and engine directory are only read, never changed, so going
back to the old version stays possible.  Article baselines are rebuilt from the
engine's stored HTML snapshots with the new extractor; that way the first live
check compares like with like and does not report formatting differences as
policy revisions, while real changes made since the snapshot are still caught.
"""
from __future__ import annotations

import logging
import shutil
import sqlite3
import time
from pathlib import Path
from typing import Callable

from . import config, db, files, monitor, site

log = logging.getLogger('wavewatch.legacy')


def _brotli() -> Callable[[bytes], bytes] | None:
    try:
        import brotli  # installed with the previous version
        return brotli.decompress
    except ImportError:
        return None


def latest_snapshot(engine_dir: Path, watch_id: str | None, decode) -> tuple[str, float] | None:
    if not watch_id or decode is None:
        return None
    folder = engine_dir / watch_id
    candidates = sorted(folder.glob('*.html.br'), key=lambda p: float(p.name.split('.')[0])) if folder.is_dir() else []
    if not candidates:
        return None
    raw = decode(candidates[-1].read_bytes())
    return raw.decode('utf-8', errors='replace'), float(candidates[-1].name.split('.')[0])


def run(legacy_path: Path | None = None, engine_dir: Path | None = None,
        decode: Callable[[bytes], bytes] | None = None) -> dict:
    legacy_path = legacy_path or config.LEGACY_DB_PATH
    engine_dir = engine_dir or legacy_path.parent / 'engine'
    decode = decode or _brotli()
    # Read-only URI; as_uri() percent-encodes the Chinese characters in the Windows path.
    old = sqlite3.connect(legacy_path.resolve().as_uri() + '?mode=ro', uri=True)
    old.row_factory = sqlite3.Row
    report = {'articles': 0, 'attachments': 0, 'entries': 0, 'from_snapshot': 0, 'rebase': 0, 'files': 0, 'events': 0}
    try:
        version = old.execute('PRAGMA user_version').fetchone()[0]
        if version != 5:
            raise RuntimeError(f'旧数据库结构版本为 {version}，只支持从版本 5 导入')
        scoped = '''EXISTS(SELECT 1 FROM article_sources m JOIN sources s ON s.id=m.source_id
                    WHERE m.article_id=a.id AND s.in_scope=1)'''
        articles = [dict(r) for r in old.execute(f'SELECT a.* FROM articles a WHERE {scoped} ORDER BY a.discovered, a.id')]
        now = time.time()
        with db.tx() as conn:
            if conn.execute('SELECT COUNT(*) FROM articles').fetchone()[0]:
                raise RuntimeError('新数据库已有数据，拒绝重复导入')
            for src in old.execute('SELECT * FROM sources WHERE in_scope=1'):
                conn.execute('UPDATE sources SET initialized=?, last_success=?, last_full=? WHERE id=?',
                             (src['initialized'], src['last_success'], src['last_success'], src['id']))
            for a in articles:
                subtitle = a['description'] if a['description'] and not a['description'].startswith('列表标题不可读') else ''
                conn.execute('''INSERT INTO articles(id,url,kind,title,subtitle,published,discovered,title_ok)
                                VALUES(?,?,?,?,?,?,?,?)''',
                             (a['id'], a['url'], a['kind'], a['title'], subtitle, a['published'], a['discovered'],
                              int(not site.bad_title(a['title']))))
                report['attachments' if a['kind'] == 'attachment' else 'articles'] += 1
            ids = {a['id'] for a in articles}
            for e in old.execute('''SELECT se.* FROM source_entries se JOIN sources s ON s.id=se.source_id
                                    WHERE s.in_scope=1'''):
                if e['article_id'] in ids:
                    conn.execute('''INSERT INTO entries(source_id,external_key,article_id,page,position,raw_title,first_seen,last_seen)
                                    VALUES(?,?,?,?,?,?,?,?)''',
                                 (e['source_id'], e['external_key'], e['article_id'], e['source_page'], e['source_position'],
                                  e['raw_title'] or '', e['first_seen'], e['last_seen']))
                    report['entries'] += 1
            for link in old.execute('SELECT * FROM article_attachments'):
                if link['parent_id'] in ids and link['attachment_id'] in ids:
                    conn.execute('INSERT OR IGNORE INTO links VALUES(?,?,?)',
                                 (link['parent_id'], link['attachment_id'], link['first_seen']))
            _import_versions(old, conn, articles, engine_dir, decode, report)
            for ev in old.execute('SELECT * FROM events'):
                if ev['article_id'] in ids:
                    kind = {'attachment_added': 'attachment_new'}.get(ev['kind'], ev['kind'])
                    if kind in ('new', 'changed'):
                        conn.execute('INSERT OR IGNORE INTO events(article_id,kind,created,read_at,route) VALUES(?,?,?,?,?)',
                                     (ev['article_id'], kind, ev['created'], None if ev['unread'] else ev['created'], 'off'))
                        report['events'] += 1
            # Re-check everything within the next hour (policy columns first) so that changes
            # made since the old version stopped are found quickly, without a burst of requests.
            order = db.rows(conn, '''SELECT a.id FROM articles a ORDER BY
                     (SELECT MIN(s.position) FROM entries e JOIN sources s ON s.id=e.source_id WHERE e.article_id=a.id), a.id''')
            for index, item in enumerate(order):
                conn.execute('UPDATE articles SET next_check=? WHERE id=?', (now + 60 + index * 3600 / max(1, len(order)), item['id']))
            db.set_setting(conn, 'legacy_import', {**report, 'at': now, 'source': str(legacy_path)})
    finally:
        old.close()
    log.info('legacy import: %s', report)
    return report


def _import_versions(old, conn, articles, engine_dir, decode, report) -> None:
    blob_paths = {r['digest']: Path(r['path']) for r in old.execute('SELECT * FROM file_blobs')}
    attachment_dir = engine_dir.parent / 'attachments'
    for a in articles:
        versions = [dict(r) for r in old.execute(
            '''SELECT v.*, fv.blob_digest FROM versions v LEFT JOIN file_versions fv ON fv.version_id=v.id
               WHERE v.article_id=? ORDER BY v.id''', (a['id'],))]
        if a['kind'] == 'attachment' or any(v['blob_digest'] for v in versions):
            for index, v in enumerate(versions):
                digest = v['blob_digest']
                if digest:
                    source = blob_paths.get(digest)
                    candidates = [p for p in (source, attachment_dir / digest) if p]
                    found = next((p for p in candidates if p.is_file()), None)
                    if found:
                        target = files.path_for(digest)
                        if not target.exists():
                            target.parent.mkdir(parents=True, exist_ok=True)
                            shutil.copyfile(found, target)
                        conn.execute('INSERT OR IGNORE INTO files(digest,bytes,created) VALUES(?,?,?)',
                                     (digest, target.stat().st_size, v['created']))
                        report['files'] += 1
                    else:
                        digest = None
                monitor.add_version(conn, a['id'], v['content'], baseline=index == 0, file_digest=digest,
                                    note='由旧版本导入', created=v['created'])
            continue
        snapshot = latest_snapshot(engine_dir, a['watch_id'], decode)
        if snapshot:
            try:
                page = site.parse_article(snapshot[0], a['url'])
                title = page.title or a['title']
                monitor.add_version(conn, a['id'], monitor.version_text(title, page.subtitle, page.text), baseline=True,
                                    note='由旧监测引擎快照导入', created=snapshot[1])
                conn.execute('UPDATE articles SET origin=?, last_check=? WHERE id=?', (page.origin, snapshot[1], a['id']))
                report['from_snapshot'] += 1
                continue
            except site.ParseError:
                pass
        for v in versions[-1:]:
            monitor.add_version(conn, a['id'], v['content'], baseline=True, note='旧版正文；下次检查按新规则重建基线',
                                created=v['created'])
        conn.execute('UPDATE articles SET rebase=1 WHERE id=?', (a['id'],))
        report['rebase'] += 1


def maybe_import() -> dict | None:
    """Called once when the new database has just been created."""
    if not config.LEGACY_DB_PATH.exists():
        return None
    try:
        return run()
    except Exception as exc:  # noqa: BLE001 - the new database stays usable; a full scan rebuilds it
        log.exception('legacy import failed')
        with db.tx() as conn:
            db.set_setting(conn, 'legacy_import', {'error': str(exc)[:300], 'at': time.time()})
        return None
