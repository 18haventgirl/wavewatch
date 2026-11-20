"""Source-scoped article inspection and bounded body/file version synchronization."""
import hashlib
from pathlib import Path
import subprocess
import sys
import time
import uuid
from sqlalchemy import select, update, insert, func
from app import collectors
from backend import queue
from backend.catalog import save_article
from backend.storage import tables as t, insert_ignore, ROOT
from backend.versions import add_version

SYNC_INTERVAL = 900


def scoped_article(conn, aid):
    a, m, s = t['articles'], t['article_sources'], t['sources']
    settings = conn.execute(select(s.c.id, s.c.hours, s.c.paused).join(m, m.c.source_id == s.c.id)
                            .where(m.c.article_id == aid, s.c.in_scope == 1)).mappings().all()
    if not settings:
        return None
    row = conn.execute(select(a).where(a.c.id == aid)).mappings().first()
    if not row:
        return None
    active = [r for r in settings if not r['paused']]
    return dict(row, paused=not active, hours=min(r['hours'] for r in (active or settings)),
                source_ids=[r['id'] for r in settings])


def state_for(conn, aid):
    state = t['monitor_states']
    insert_ignore(conn, state, dict(article_id=aid), ['article_id'])
    return dict(conn.execute(select(state).where(state.c.article_id == aid)).mappings().one())


def complete(conn, job, **values):
    conn.execute(update(t['monitor_states']).where(
        t['monitor_states'].c.article_id == job['payload']['article_id']).values(**values))
    queue.finish(conn, job)


def inspect_article(engine, job):
    aid = job['payload']['article_id']
    with engine.begin() as conn:
        article = scoped_article(conn, aid)
        state = state_for(conn, aid) if article else None
    if not article or article['paused'] or article['kind'] == 'attachment':
        with engine.begin() as conn:
            queue.finish(conn, job)
        return
    body, ctype = collectors.fetch(article['url'])
    if is_file(article) or ('html' not in ctype and body.startswith(b'%PDF')):
        with engine.begin() as conn:
            complete(conn, job, next_inspect=time.time() + article['hours'] * 3600,
                     last_inspect=time.time(), inspect_error='')
        return
    soup = collectors.soup_of(body)
    main = soup.select_one('.u-art-box')
    if not main or len(main.get_text(' ', strip=True)) < 20:
        raise ValueError('Official article body was not found')
    title = collectors.article_title(body)
    items = collectors.attachments(article['url'], body)
    with engine.begin() as conn:
        current = scoped_article(conn, aid)
        if not current or current['paused']:
            queue.finish(conn, job)
            return
        if title and not collectors.bad_title(title):
            conn.execute(update(t['articles']).where(t['articles'].c.id == aid).values(title=title))
        for item in items:
            for sid in current['source_ids']:
                save_article(conn, sid, item | {'parent_id': aid}, baseline=state['last_inspect'] is None)
        complete(conn, job, next_inspect=time.time() + current['hours'] * 3600,
                 last_inspect=time.time(), inspect_error='')


def is_file(article):
    return article['kind'] == 'attachment' or any(
        collectors.urlsplit(article['url']).path.lower().endswith(ext)
        for ext in ('.pdf', '.doc', '.docx', '.xls', '.xlsx', '.zip'))


def save_blob(root, body):
    digest = hashlib.sha256(body).hexdigest()
    folder = Path(root).resolve() / 'attachments'
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / digest
    if target.exists():
        if hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise ValueError('Stored attachment checksum mismatch')
    else:
        temporary = folder / (digest + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_bytes(body)
            temporary.replace(target)
        finally:
            temporary.unlink(missing_ok=True)
    return digest, target


def file_text(body, file, digest):
    content = '附件字节指纹变化，不自动等于政策内容变化。\nSHA-256: ' + digest + '\n文件大小: ' + str(len(body)) + ' 字节\n'
    if body.startswith(b'%PDF'):
        try:
            result = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / 'scripts' / 'extract_pdf.py'), str(file)],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=20)
            content += result.stdout if result.returncode == 0 else 'PDF 文本提取未完成，完整文件已保存。'
        except subprocess.TimeoutExpired:
            content += 'PDF 文本提取超时，完整文件已保存。'
    else:
        content += '此格式提供文件指纹和保存版本。'
    return content


def sync_file(engine, job, article, root):
    body, ctype = collectors.fetch(article['url'])
    if not body or 'html' in ctype.lower() or body.lstrip().lower().startswith((b'<!doctype html', b'<html')):
        raise ValueError('Attachment URL returned HTML or an empty response')
    digest, file = save_blob(root, body)
    content = file_text(body, file, digest)
    with engine.begin() as conn:
        current = scoped_article(conn, article['id'])
        if not current or current['paused']:
            queue.finish(conn, job)
            return
        insert_ignore(conn, t['file_blobs'], dict(digest=digest, path='attachments/' + digest,
                                                bytes=len(body)), ['digest'])
        # Stamp identifies this observation, not the digest: A -> B -> A retains three versions.
        previous = conn.execute(select(t['file_versions'].c.version_id, t['file_versions'].c.blob_digest)
            .join(t['versions'], t['versions'].c.id == t['file_versions'].c.version_id)
            .where(t['versions'].c.article_id == article['id']).order_by(t['versions'].c.id.desc()).limit(1)).mappings().first()
        if previous and previous['blob_digest'] == digest:
            vid = previous['version_id']
        else:
            vid, _ = add_version(conn, article['id'], 'file:' + job['id'], content)
        insert_ignore(conn, t['file_versions'], dict(version_id=vid, blob_digest=digest), ['version_id'])
        insert_ignore(conn, t['file_checks'], dict(article_id=article['id'], checked=time.time()), ['article_id'])
        conn.execute(update(t['file_checks']).where(t['file_checks'].c.article_id == article['id']).values(checked=time.time()))
        complete(conn, job, next_sync=time.time() + current['hours'] * 3600,
                 last_sync=time.time(), sync_error='')


def sync_article(engine, job, client, root):
    aid = job['payload']['article_id']
    with engine.begin() as conn:
        article = scoped_article(conn, aid)
        state = state_for(conn, aid) if article else None
    if not article:
        with engine.begin() as conn:
            queue.finish(conn, job)
        return
    if is_file(article):
        if article['paused']:
            with engine.begin() as conn:
                queue.finish(conn, job)
            return
        return sync_file(engine, job, article, root)
    wid = client.ensure_watch(article, article['hours'], article['paused'])
    if not wid:
        with engine.begin() as conn:
            complete(conn, job, engine_paused=1, next_sync=time.time() + SYNC_INTERVAL)
        return
    watch = client.api(client.path(wid))
    if not isinstance(watch, dict) or watch.get('url') != article['url']:
        raise ValueError('Engine watch URL does not match the article')
    filters = ['.u-art-box']
    patch = {}
    if bool(watch.get('paused')) != article['paused']:
        patch['paused'] = article['paused']
    if watch.get('time_between_check', {}).get('hours') != article['hours'] or watch.get('time_between_check_use_default'):
        patch.update(time_between_check={'hours': article['hours']}, time_between_check_use_default=False)
    if not watch.get('notification_muted'):
        patch['notification_muted'] = True
    if watch.get('title') != article['title']:
        patch['title'] = article['title']
    rebase = watch.get('include_filters', []) != filters
    history = client.api(client.path(wid, '/history')) if not article['paused'] else {}
    if not isinstance(history, dict):
        raise ValueError('Invalid engine history')
    stamps = sorted(history, key=float)
    if rebase and not article['paused']:
        patch['include_filters'] = filters
    if rebase and not article['paused']:
        # Persist pending rebase BEFORE changing the engine filters. A retry cannot
        # accidentally import a filter change as a policy revision.
        with engine.begin() as conn:
            queue.assert_lease(conn, job)
            conn.execute(update(t['articles']).where(t['articles'].c.id == aid).values(watch_id=wid))
            conn.execute(update(t['monitor_states']).where(t['monitor_states'].c.article_id == aid).values(
                rebase_after=float(stamps[-1]) if stamps else 0,
                sync_error='正文筛选规则调整，等待新基线'))
        if patch:
            client.api(client.path(wid), 'PUT', patch)
        client.api(client.path(wid, '?recheck=1'))
        with engine.begin() as conn:
            complete(conn, job, engine_paused=0, next_sync=time.time() + 30)
        return
    if patch:
        client.api(client.path(wid), 'PUT', patch)
    if article['paused']:
        with engine.begin() as conn:
            conn.execute(update(t['articles']).where(t['articles'].c.id == aid).values(watch_id=wid))
            complete(conn, job, engine_paused=1, next_sync=time.time() + SYNC_INTERVAL)
        return
    if watch.get('last_error'):
        raise ValueError('Engine has not produced a valid article snapshot')
    with engine.connect() as conn:
        existing = set(conn.scalars(select(t['versions'].c.stamp).where(t['versions'].c.article_id == aid)))
    cutoff = max(state['history_cursor'] or 0, state['rebase_after'] or 0)
    pending = [s for s in stamps if float(s) > cutoff and str(s) not in existing]
    snapshots = []
    for stamp in pending[:20]:
        content = client.api(client.path(wid, '/history/' + str(stamp)))
        if not isinstance(content, str) or not 20 <= len(content.strip()) <= 4 * 1024 * 1024:
            raise ValueError('Snapshot is empty, too short or too large')
        collectors.soup_of(content.encode())
        snapshots.append((str(stamp), content))
    with engine.begin() as conn:
        current = scoped_article(conn, aid)
        if not current or current['paused']:
            queue.finish(conn, job)
            return
        rebase_pending = state['rebase_after'] is not None
        for stamp, content in snapshots:
            add_version(conn, aid, stamp, content, baseline=rebase_pending)
            rebase_pending = False
        conn.execute(update(t['articles']).where(t['articles'].c.id == aid).values(watch_id=wid))
        values = dict(engine_paused=0, next_sync=time.time() + (30 if len(pending) > 20 else SYNC_INTERVAL),
                      last_sync=time.time() if snapshots else state['last_sync'],
                      sync_error='' if snapshots or stamps else '等待引擎首次快照')
        if state['rebase_after'] is not None and snapshots:
            values['rebase_after'] = None
        if snapshots:
            values['history_cursor'] = float(snapshots[-1][0])
        complete(conn, job, **values)
