"""HTTP API and static front end.  Listens on 127.0.0.1 only."""
from __future__ import annotations

import json
import logging
import re
import time
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

import os
import subprocess
import sys
from pathlib import Path

from . import config, db, diffing, files, legacy, monitor, notify, power, worker

log = logging.getLogger('wavewatch.api')
STARTED = time.time()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    if db.init():
        legacy.maybe_import()
    if not getattr(_app.state, 'no_workers', False):
        worker.start()
    yield
    worker.shutdown()


app = FastAPI(title=config.APP_NAME, lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)


@app.middleware('http')
async def local_only(request: Request, call_next):
    # Reject anything not addressed to this machine (also blocks DNS-rebinding),
    # and cross-site writes from other pages open in the browser.
    if request.url.hostname not in ('127.0.0.1', 'localhost', 'testserver'):
        return JSONResponse({'detail': '仅允许本机访问'}, status_code=403)
    origin = request.headers.get('origin')
    if request.method not in ('GET', 'HEAD', 'OPTIONS') and origin and urlsplit(origin).netloc != request.url.netloc:
        return JSONResponse({'detail': '请求来源不符'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


def bj_midnight(now: float) -> float:
    local = datetime.fromtimestamp(now, config.BEIJING)
    return local.replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


def column_map(conn, ids: list[str]) -> dict[str, list[dict]]:
    if not ids:
        return {}
    marks = ','.join('?' * len(ids))
    out: dict[str, list[dict]] = {i: [] for i in ids}
    for r in conn.execute(f'''SELECT DISTINCT e.article_id, s.id, s.name, s.role, s.grp, s.position
                              FROM entries e JOIN sources s ON s.id=e.source_id
                              WHERE e.article_id IN ({marks}) AND s.configured=1 ORDER BY s.position''', ids):
        out[r['article_id']].append({'id': r['id'], 'name': r['name'], 'role': r['role'], 'group': r['grp']})
    # Attachments inherit the columns of the articles that link them.
    for r in conn.execute(f'''SELECT DISTINCT l.attachment_id, s.id, s.name, s.role, s.grp, s.position
                              FROM links l JOIN entries e ON e.article_id=l.parent_id JOIN sources s ON s.id=e.source_id
                              WHERE l.attachment_id IN ({marks}) AND s.configured=1 ORDER BY s.position''', ids):
        if not any(c['id'] == r['id'] for c in out[r['attachment_id']]):
            out[r['attachment_id']].append({'id': r['id'], 'name': r['name'], 'role': r['role'], 'group': r['grp']})
    return out


# --- overview ------------------------------------------------------------------------------------

@app.get('/api/overview')
def overview():
    now = time.time()
    today = bj_midnight(now)
    with db.tx() as conn:
        stats = {
            'articles': conn.execute("SELECT COUNT(*) FROM articles WHERE kind='article'").fetchone()[0],
            'attachments': conn.execute("SELECT COUNT(*) FROM articles WHERE kind='attachment'").fetchone()[0],
            'unread': conn.execute('SELECT COUNT(DISTINCT article_id) FROM events WHERE read_at IS NULL').fetchone()[0],
            'today_new': conn.execute("SELECT COUNT(*) FROM events WHERE kind='new' AND created>=?", (today,)).fetchone()[0],
            'today_changed': conn.execute("SELECT COUNT(*) FROM events WHERE kind!='new' AND created>=?", (today,)).fetchone()[0],
            'week_events': conn.execute('SELECT COUNT(*) FROM events WHERE created>=?', (now - 7 * 86400,)).fetchone()[0],
            'check_errors': conn.execute(f"SELECT COUNT(*) FROM articles a WHERE check_error!='' AND {monitor.ACTIVE_ARTICLE}").fetchone()[0],
            'due': conn.execute(f'SELECT COUNT(*) FROM articles a WHERE next_check<=? AND {monitor.ACTIVE_ARTICLE}', (now,)).fetchone()[0],
            'never_checked': conn.execute(f'SELECT COUNT(*) FROM articles a WHERE last_check IS NULL AND {monitor.ACTIVE_ARTICLE}').fetchone()[0],
        }
        settings = notify.load(conn)
        email = {
            'enabled': settings['enabled'], 'ready': notify.ready(settings), 'recipients': len(settings['recipients']),
            'digest_time': settings['digest_time'],
            'pending': conn.execute("SELECT COUNT(*) FROM emails WHERE state='pending'").fetchone()[0],
            'failed': conn.execute("SELECT COUNT(*) FROM emails WHERE state='failed' AND created>=?", (now - 86400,)).fetchone()[0],
            'last_sent': conn.execute("SELECT MAX(sent_at) FROM emails WHERE state='sent'").fetchone()[0],
            'last_error': (db.row(conn, "SELECT last_error FROM emails WHERE last_error!='' ORDER BY id DESC LIMIT 1") or {}).get('last_error', ''),
        }
        result = {
            'now': now, 'started': STARTED, 'stats': stats, 'email': email,
            'sources': list_sources(conn),
            'recent': event_rows(conn, 'WHERE 1', [], 8, 0),
            'workers': worker.status, 'healthy': worker.healthy(),
            'import': db.get_setting(conn, 'legacy_import'),
        }
    return result


# --- columns -------------------------------------------------------------------------------------

def list_sources(conn) -> list[dict]:
    sources = db.rows(conn, 'SELECT * FROM sources WHERE configured=1 ORDER BY position')
    for s in sources:
        s['page_url'] = config.source_page_url(s['column_id'])
        s['articles'] = conn.execute('SELECT COUNT(DISTINCT article_id) FROM entries WHERE source_id=?', (s['id'],)).fetchone()[0]
        s['unread'] = conn.execute('''SELECT COUNT(DISTINCT ev.article_id) FROM events ev
                                      WHERE ev.read_at IS NULL AND ev.article_id IN (SELECT article_id FROM entries WHERE source_id=?)''',
                                   (s['id'],)).fetchone()[0]
        s['last_run'] = db.row(conn, 'SELECT * FROM runs WHERE source_id=? ORDER BY id DESC LIMIT 1', (s['id'],))
        s['history'] = list(reversed(db.rows(conn, '''SELECT started, state, added, mode FROM runs WHERE source_id=?
                                                     ORDER BY id DESC LIMIT 96''', (s['id'],))))
        s['last_added'] = db.row(conn, "SELECT MAX(finished) AS at, SUM(added) AS total FROM runs WHERE source_id=? AND added>0",
                                 (s['id'],))
    return sources


@app.get('/api/sources')
def sources():
    with db.tx() as conn:
        return list_sources(conn)


class SourcePatch(BaseModel):
    enabled: bool | None = None
    list_minutes: int | None = Field(None, ge=1, le=1440)
    article_hours: int | None = Field(None, ge=1, le=168)
    notify: Literal['instant', 'digest', 'off'] | None = None


@app.patch('/api/sources/{source_id}')
def update_source(source_id: str, patch: SourcePatch):
    changes = patch.model_dump(exclude_none=True)
    with db.tx() as conn:
        src = db.row(conn, 'SELECT * FROM sources WHERE id=? AND configured=1', (source_id,))
        if not src:
            raise HTTPException(404, '栏目不存在')
        if changes:
            conn.execute(f"UPDATE sources SET {', '.join(k + '=?' for k in changes)} WHERE id=?",
                         [int(v) if isinstance(v, bool) else v for v in changes.values()] + [source_id])
        now = time.time()
        if 'list_minutes' in changes or (changes.get('enabled') and not src['enabled']):
            soon = now if changes.get('enabled') and not src['enabled'] else now + changes.get('list_minutes', src['list_minutes']) * 60
            conn.execute('UPDATE sources SET next_check=MIN(next_check, ?) WHERE id=?', (soon, source_id))
        if 'article_hours' in changes:
            # Bring forward articles whose next check is now later than the new interval allows.
            conn.execute('''UPDATE articles SET next_check=MIN(next_check, COALESCE(last_check, 0) + ?)
                            WHERE id IN (SELECT article_id FROM entries WHERE source_id=?)''',
                         (changes['article_hours'] * 3600, source_id))
        result = next(s for s in list_sources(conn) if s['id'] == source_id)
    worker.wake_lists.set()
    worker.wake_content.set()
    return result


class CheckRequest(BaseModel):
    full: bool = False


@app.post('/api/sources/{source_id}/check')
def check_source(source_id: str, body: CheckRequest = CheckRequest()):
    if not monitor.request_source(source_id, body.full):
        raise HTTPException(404, '栏目不存在')
    worker.wake_lists.set()
    return {'ok': True}


@app.post('/api/check')
def check_all(body: CheckRequest = CheckRequest()):
    with db.tx() as conn:
        ids = [r[0] for r in conn.execute('SELECT id FROM sources WHERE configured=1 AND enabled=1')]
    for source_id in ids:
        monitor.request_source(source_id, body.full)
    worker.wake_lists.set()
    return {'queued': len(ids)}


@app.get('/api/runs')
def runs(source: str = '', state: str = '', changes_only: bool = False, page: int = 1, size: int = 50):
    size = max(1, min(size, 200))
    where, args = ['1'], []
    if source:
        where.append('r.source_id=?')
        args.append(source)
    if state in ('ok', 'error', 'running', 'interrupted'):
        where.append('r.state=?')
        args.append(state)
    if changes_only:
        where.append("(r.added>0 OR r.state!='ok' OR r.mode='full')")
    clause = ' AND '.join(where)
    with db.tx() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM runs r WHERE {clause}', args).fetchone()[0]
        items = db.rows(conn, f'''SELECT r.*, s.name FROM runs r JOIN sources s ON s.id=r.source_id
                                  WHERE {clause} ORDER BY r.id DESC LIMIT ? OFFSET ?''', args + [size, (max(page, 1) - 1) * size])
        problems = db.rows(conn, f'''SELECT a.id, a.title, a.url, a.check_error, a.fail_count, a.last_check, a.next_check
                                     FROM articles a WHERE a.check_error!='' AND {monitor.ACTIVE_ARTICLE}
                                     ORDER BY a.fail_count DESC LIMIT 50''')
    return {'items': items, 'total': total, 'page': page, 'size': size, 'article_errors': problems}


# --- events (updates) -------------------------------------------------------------------------------

def event_rows(conn, where: str, args: list, limit: int, offset: int) -> list[dict]:
    items = db.rows(conn, f'''
        SELECT e.id, e.kind, e.created, e.summary, e.read_at, e.route, e.email_id, e.version_id,
               a.id AS article_id, a.title, a.url, a.published, a.kind AS article_kind,
               c.id AS attachment_id, c.title AS attachment_title
        FROM events e JOIN articles a ON a.id=e.article_id LEFT JOIN articles c ON c.id=e.attachment_id
        {where} ORDER BY e.created DESC, e.id DESC LIMIT ? OFFSET ?''', args + [limit, offset])
    columns = column_map(conn, list({i['article_id'] for i in items}))
    for item in items:
        item['columns'] = columns.get(item['article_id'], [])
    return items


@app.get('/api/events')
def events(kind: str = '', source: str = '', unread: bool = False, q: str = '', page: int = 1, size: int = 30):
    size = max(1, min(size, 100))
    where, args = ['1'], []
    if kind == 'changes':
        where.append("e.kind!='new'")
    elif kind in ('new', 'changed', 'attachment_new', 'attachment_changed'):
        where.append('e.kind=?')
        args.append(kind)
    if source:
        where.append('e.article_id IN (SELECT article_id FROM entries WHERE source_id=?)')
        args.append(source)
    if unread:
        where.append('e.read_at IS NULL')
    if q.strip():
        where.append('a.title LIKE ?')
        args.append(f'%{q.strip()[:100]}%')
    clause = 'WHERE ' + ' AND '.join(where)
    with db.tx() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM events e JOIN articles a ON a.id=e.article_id {clause}', args).fetchone()[0]
        unread_total = conn.execute('SELECT COUNT(*) FROM events WHERE read_at IS NULL').fetchone()[0]
        return {'items': event_rows(conn, clause, args, size, (max(page, 1) - 1) * size),
                'total': total, 'unread': unread_total, 'page': page, 'size': size}


class ReadRequest(BaseModel):
    ids: list[int] = []
    articles: list[str] = []
    all: bool = False
    source: str = ''
    read: bool = True


@app.post('/api/events/read')
def mark_events(body: ReadRequest):
    value = time.time() if body.read else None
    with db.tx() as conn:
        if body.all:
            if body.source:
                n = conn.execute('''UPDATE events SET read_at=? WHERE read_at IS NULL AND article_id IN
                                    (SELECT article_id FROM entries WHERE source_id=?)''', (value, body.source)).rowcount
            else:
                n = conn.execute('UPDATE events SET read_at=? WHERE read_at IS NULL', (value,)).rowcount
        else:
            n = 0
            for chunk in (body.ids[i:i + 500] for i in range(0, len(body.ids), 500)):
                n += conn.execute(f"UPDATE events SET read_at=? WHERE id IN ({','.join('?' * len(chunk))})",
                                  [value, *chunk]).rowcount
            for chunk in (body.articles[i:i + 500] for i in range(0, len(body.articles), 500)):
                n += conn.execute(f"UPDATE events SET read_at=? WHERE article_id IN ({','.join('?' * len(chunk))})",
                                  [value, *chunk]).rowcount
    return {'updated': n}


# --- articles ------------------------------------------------------------------------------------

SORTS = {
    'published': "COALESCE(a.published,'') DESC, a.discovered DESC",
    'discovered': 'a.discovered DESC',
    'updated': 'COALESCE((SELECT MAX(created) FROM events WHERE article_id=a.id), a.discovered) DESC',
    'official': 'official_position IS NULL, official_position',
}


@app.get('/api/articles')
def articles(q: str = '', source: str = '', group: str = '', status: str = '', sort: str = 'published',
             page: int = 1, size: int = 30, include_attachments: bool = False):
    size = max(1, min(size, 100))
    where, args = ['1'], []
    if not include_attachments:
        where.append("(a.kind='article' OR EXISTS(SELECT 1 FROM entries WHERE article_id=a.id))")
    if q.strip():
        terms = q.strip()[:100].split()
        for term in terms:
            where.append('(a.title LIKE ? OR a.subtitle LIKE ? OR a.origin LIKE ?)')
            args += [f'%{term}%'] * 3
    if source:
        where.append('EXISTS(SELECT 1 FROM entries WHERE article_id=a.id AND source_id=?)')
        args.append(source)
    elif group in ('core', 'news'):
        where.append('EXISTS(SELECT 1 FROM entries x JOIN sources s ON s.id=x.source_id WHERE x.article_id=a.id AND s.role=?)')
        args.append(group)
    if status == 'unread':
        where.append('EXISTS(SELECT 1 FROM events WHERE article_id=a.id AND read_at IS NULL)')
    elif status == 'changed':
        where.append("EXISTS(SELECT 1 FROM events WHERE article_id=a.id AND kind!='new')")
    elif status == 'error':
        where.append("a.check_error!=''")
    elif status == 'attachments':
        where.append('EXISTS(SELECT 1 FROM links WHERE parent_id=a.id)')
    if sort == 'official' and not source:
        sort = 'published'
    order = SORTS.get(sort, SORTS['published'])
    position = '(SELECT MIN(position) FROM entries WHERE article_id=a.id AND source_id=?) AS official_position,' if sort == 'official' else ''
    clause = ' AND '.join(where)
    with db.tx() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM articles a WHERE {clause}', args).fetchone()[0]
        items = db.rows(conn, f'''
            SELECT {position} a.id, a.url, a.kind, a.title, a.subtitle, a.origin, a.published, a.discovered,
                   a.last_check, a.next_check, a.check_error, a.title_ok,
                   (SELECT COUNT(*) FROM versions WHERE article_id=a.id) AS versions,
                   (SELECT COUNT(*) FROM links WHERE parent_id=a.id) AS attachments,
                   (SELECT COUNT(*) FROM events WHERE article_id=a.id AND read_at IS NULL) AS unread,
                   (SELECT COUNT(*) FROM events WHERE article_id=a.id AND kind!='new') AS changes,
                   (SELECT MAX(created) FROM events WHERE article_id=a.id) AS last_event
            FROM articles a WHERE {clause} ORDER BY {order}, a.id LIMIT ? OFFSET ?''',
            ([source] if position else []) + args + [size, (max(page, 1) - 1) * size])
        columns = column_map(conn, [i['id'] for i in items])
        for item in items:
            item['columns'] = columns.get(item['id'], [])
    return {'items': items, 'total': total, 'page': page, 'size': size}


def version_list(conn, article_id: str) -> list[dict]:
    return db.rows(conn, '''SELECT v.id, v.created, v.digest, v.baseline, v.note, v.file_digest, LENGTH(v.content) AS length,
                                   f.bytes AS file_bytes
                            FROM versions v LEFT JOIN files f ON f.digest=v.file_digest
                            WHERE v.article_id=? ORDER BY v.id DESC''', (article_id,))


@app.get('/api/articles/{article_id}')
def article(article_id: str):
    with db.tx() as conn:
        item = db.row(conn, 'SELECT * FROM articles WHERE id=?', (article_id,))
        if not item:
            raise HTTPException(404, '没有找到这条信息')
        item['columns'] = column_map(conn, [article_id])[article_id]
        item['entries'] = db.rows(conn, '''SELECT e.source_id, s.name, e.page, e.position, e.first_seen, e.last_seen, e.raw_title
                                          FROM entries e JOIN sources s ON s.id=e.source_id WHERE e.article_id=?''', (article_id,))
        item['versions'] = version_list(conn, article_id)
        latest = db.row(conn, 'SELECT content FROM versions WHERE article_id=? ORDER BY id DESC LIMIT 1', (article_id,))
        item['content'] = latest['content'] if latest else ''
        item['attachments'] = db.rows(conn, '''
            SELECT a.id, a.url, a.title, a.last_check, a.check_error,
                   (SELECT file_digest FROM versions WHERE article_id=a.id ORDER BY id DESC LIMIT 1) AS file_digest,
                   (SELECT COUNT(*) FROM versions WHERE article_id=a.id) AS versions,
                   (SELECT f.bytes FROM versions v JOIN files f ON f.digest=v.file_digest WHERE v.article_id=a.id ORDER BY v.id DESC LIMIT 1) AS bytes
            FROM links l JOIN articles a ON a.id=l.attachment_id WHERE l.parent_id=? ORDER BY l.first_seen''', (article_id,))
        item['parents'] = db.rows(conn, '''SELECT a.id, a.title FROM links l JOIN articles a ON a.id=l.parent_id
                                          WHERE l.attachment_id=?''', (article_id,))
        item['events'] = event_rows(conn, 'WHERE e.article_id=?', [article_id], 50, 0)
        item['source_url'] = item['url']
    return item


@app.get('/api/articles/{article_id}/versions/{version_id}')
def version(article_id: str, version_id: int):
    with db.tx() as conn:
        found = db.row(conn, 'SELECT * FROM versions WHERE id=? AND article_id=?', (version_id, article_id))
    if not found:
        raise HTTPException(404, '没有找到该版本')
    return found


@app.get('/api/articles/{article_id}/compare')
def compare(article_id: str, base: int | None = None, target: int | None = None):
    with db.tx() as conn:
        versions = db.rows(conn, 'SELECT id, created, content FROM versions WHERE article_id=? ORDER BY id DESC', (article_id,))
    if len(versions) < 2:
        return {'rows': [], 'base': None, 'target': versions[0]['id'] if versions else None, 'stats': {'added': 0, 'removed': 0}}
    by_id = {v['id']: v for v in versions}
    new = by_id.get(target) if target else versions[0]
    if not new:
        raise HTTPException(404, '没有找到该版本')
    older = [v for v in versions if v['id'] < new['id']]
    old = by_id.get(base) if base else (older[0] if older else None)
    if not old:
        raise HTTPException(400, '没有可比较的更早版本')
    return {'base': old['id'], 'target': new['id'], 'rows': diffing.compare(old['content'], new['content']),
            'stats': diffing.stats(old['content'], new['content'])}


@app.post('/api/articles/{article_id}/check')
def check_article(article_id: str):
    if not monitor.request_article(article_id):
        raise HTTPException(404, '没有找到这条信息')
    worker.wake_content.set()
    return {'ok': True}


@app.get('/api/files/{digest}')
def download(digest: str, name: str = ''):
    if not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise HTTPException(404, '文件不存在')
    with db.tx() as conn:
        known = db.row(conn, 'SELECT * FROM files WHERE digest=?', (digest,))
        title = db.row(conn, '''SELECT a.title, a.url FROM versions v JOIN articles a ON a.id=v.article_id
                                WHERE v.file_digest=? ORDER BY v.id DESC LIMIT 1''', (digest,))
    path = files.path_for(digest)
    if not known or not path.is_file():
        raise HTTPException(404, '文件尚未保存到本机')
    suffix = ''
    if title:
        match = re.search(r'\.[A-Za-z0-9]{2,5}$', urlsplit(title['url']).path)
        suffix = match.group(0) if match else ''
    filename = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', name or (title['title'] if title else digest))[:150]
    if suffix and not filename.lower().endswith(suffix.lower()):
        filename += suffix
    return FileResponse(path, filename=filename, media_type='application/octet-stream')


# --- e-mail ---------------------------------------------------------------------------------------

EMAIL_RE = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')


class EmailSettings(BaseModel):
    enabled: bool | None = None
    host: str | None = Field(None, max_length=200)
    port: int | None = Field(None, ge=1, le=65535)
    security: Literal['ssl', 'starttls', 'none'] | None = None
    username: str | None = Field(None, max_length=200)
    password: str | None = Field(None, max_length=500)
    clear_password: bool = False
    sender: str | None = Field(None, max_length=200)
    sender_name: str | None = Field(None, max_length=60)
    recipients: list[str] | None = None
    merge_minutes: int | None = Field(None, ge=0, le=120)
    digest_time: str | None = None
    digest_include_instant: bool | None = None
    digest_send_empty: bool | None = None
    alert_failures: int | None = Field(None, ge=1, le=50)

    @field_validator('recipients')
    @classmethod
    def _recipients(cls, value):
        if value is None:
            return value
        cleaned = list(dict.fromkeys(v.strip() for v in value if v.strip()))
        bad = [v for v in cleaned if not EMAIL_RE.match(v)]
        if bad:
            raise ValueError('收件地址格式不正确：' + '、'.join(bad))
        if len(cleaned) > 20:
            raise ValueError('收件人最多 20 个')
        return cleaned

    @field_validator('digest_time')
    @classmethod
    def _time(cls, value):
        if value is not None and not re.fullmatch(r'([01]\d|2[0-3]):[0-5]\d', value):
            raise ValueError('汇总时间格式应为 HH:MM')
        return value

    @field_validator('sender')
    @classmethod
    def _sender(cls, value):
        if value and not EMAIL_RE.match(value.strip()):
            raise ValueError('发件地址格式不正确')
        return value.strip() if value else value


@app.get('/api/email')
def email_settings():
    with db.tx() as conn:
        return notify.public(notify.load(conn))


@app.put('/api/email')
def save_email(body: EmailSettings):
    changes = body.model_dump(exclude_none=True)
    with db.tx() as conn:
        current = notify.load(conn)
        merged = {**current, **changes}
        if merged.get('enabled') and (not merged.get('host') or not merged.get('recipients')):
            raise HTTPException(400, '开启邮件通知前，请填写邮件服务器和至少一个收件人')
        saved = notify.save(conn, changes)
    worker.wake_mail.set()
    return notify.public(saved)


class TestRequest(BaseModel):
    password: str | None = None


@app.post('/api/email/test')
def test_email(body: TestRequest = TestRequest()):
    override = {}
    if body.password:
        from . import secret
        override['password'] = secret.seal(body.password)
    return notify.send_test(override)


@app.post('/api/email/digest')
def digest_now():
    email_id = notify.queue_digest(force=True)
    if not email_id:
        raise HTTPException(400, '邮件通知尚未开启或配置不完整')
    worker.wake_mail.set()
    return {'queued': email_id}


@app.get('/api/emails')
def emails(page: int = 1, size: int = 30, state: str = ''):
    size = max(1, min(size, 100))
    where, args = ('WHERE state=?', [state]) if state in ('pending', 'sent', 'failed') else ('', [])
    with db.tx() as conn:
        total = conn.execute(f'SELECT COUNT(*) FROM emails {where}', args).fetchone()[0]
        items = db.rows(conn, f'''SELECT id, kind, subject, recipients, created, state, attempts, next_attempt, last_error, sent_at,
                                         (SELECT COUNT(*) FROM events WHERE email_id=emails.id) AS events
                                  FROM emails {where} ORDER BY id DESC LIMIT ? OFFSET ?''', args + [size, (max(page, 1) - 1) * size])
    for item in items:
        item['recipients'] = json.loads(item['recipients'])
    return {'items': items, 'total': total, 'page': page, 'size': size}


@app.get('/api/emails/{email_id}/preview', response_class=HTMLResponse)
def email_preview(email_id: int):
    with db.tx() as conn:
        found = db.row(conn, 'SELECT html_body, text_body FROM emails WHERE id=?', (email_id,))
    if not found:
        raise HTTPException(404, '邮件不存在')
    return HTMLResponse(found['html_body'] or f"<pre>{found['text_body']}</pre>",
                        headers={'Content-Security-Policy': "default-src 'none'; style-src 'unsafe-inline'; img-src data:"})


@app.post('/api/emails/{email_id}/retry')
def retry_email(email_id: int):
    with db.tx() as conn:
        n = conn.execute("UPDATE emails SET state='pending', next_attempt=0 WHERE id=? AND state!='sent'", (email_id,)).rowcount
    if not n:
        raise HTTPException(400, '这封邮件已发送或不存在')
    worker.wake_mail.set()
    return {'ok': True}


# --- this computer -------------------------------------------------------------------------------

def startup_link() -> Path | None:
    appdata = os.getenv('APPDATA')
    if sys.platform != 'win32' or not appdata:
        return None
    return Path(appdata) / 'Microsoft' / 'Windows' / 'Start Menu' / 'Programs' / 'Startup' / 'Wavewatch THVS.lnk'


def system_state() -> dict:
    with db.tx() as conn:
        keep = bool(db.get_setting(conn, 'keep_awake', True))
    link = startup_link()
    return {'keep_awake': keep, 'keep_awake_supported': power.SUPPORTED,
            'autostart': bool(link and link.exists()), 'autostart_supported': link is not None,
            'data_dir': str(config.DATA), 'url': config.LOCAL_URL}


class SystemSettings(BaseModel):
    keep_awake: bool | None = None
    autostart: bool | None = None


@app.get('/api/system')
def system():
    return system_state()


@app.put('/api/system')
def update_system(body: SystemSettings):
    if body.keep_awake is not None:
        with db.tx() as conn:
            db.set_setting(conn, 'keep_awake', body.keep_awake)
    if body.autostart is not None:
        if startup_link() is None:
            raise HTTPException(400, '开机自启只在 Windows 上可用')
        script = config.ROOT / 'scripts' / 'autostart.ps1'
        args = ['powershell', '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script)]
        result = subprocess.run(args + ([] if body.autostart else ['-Disable']), capture_output=True, text=True,
                                timeout=30, creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
        if result.returncode != 0:
            raise HTTPException(500, '设置开机自启失败：' + (result.stderr or result.stdout).strip()[:200])
    return system_state()


# --- health & front end ----------------------------------------------------------------------------

@app.get('/api/health')
def health():
    return {'ok': worker.healthy(), 'workers': worker.status, 'started': STARTED, 'now': time.time()}


if (config.FRONTEND_DIST / 'assets').exists():
    app.mount('/assets', StaticFiles(directory=config.FRONTEND_DIST / 'assets'), name='assets')


@app.get('/', include_in_schema=False)
def home():
    index = config.FRONTEND_DIST / 'index.html'
    if not index.exists():
        return HTMLResponse('<h3>前端尚未构建</h3><p>请运行 <code>.\\start.ps1 -Install</code>。</p>', status_code=503)
    return FileResponse(index, headers={'Cache-Control': 'no-cache'})
