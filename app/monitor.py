"""Monitoring work: column list checks, article body checks and attachment checks.

Every function here does network I/O outside of database transactions and then
records the outcome in one short transaction.  Events (new / changed) are written
in the same transaction as the data that caused them, so a crash can never leave
an orphan notification or a silent change.
"""
from __future__ import annotations

import hashlib
import logging
import sqlite3
import time

from . import config, db, diffing, fetch, files, site

log = logging.getLogger('guanlan.monitor')

NOTIFY_RANK = {'instant': 2, 'digest': 1, 'off': 0}


# --- shared helpers ----------------------------------------------------------------------

def route_for(conn: sqlite3.Connection, article_id: str) -> str:
    """Strongest notification mode among the columns that list this article."""
    modes = [r['notify'] for r in conn.execute(
        '''SELECT DISTINCT s.notify FROM entries e JOIN sources s ON s.id=e.source_id
           WHERE e.article_id=? AND s.configured=1''', (article_id,))]
    return max(modes, key=NOTIFY_RANK.get) if modes else 'off'


def add_event(conn: sqlite3.Connection, article_id: str, kind: str, *, attachment_id: str | None = None,
              version_id: int | None = None, summary: str = '') -> None:
    conn.execute(
        '''INSERT OR IGNORE INTO events(article_id,attachment_id,version_id,kind,created,summary,route)
           VALUES(?,?,?,?,?,?,?)''',
        (article_id, attachment_id, version_id, kind, time.time(), summary, route_for(conn, article_id)))


def add_version(conn: sqlite3.Connection, article_id: str, content: str, *, baseline: bool,
                file_digest: str | None = None, note: str = '', created: float | None = None) -> int:
    digest = file_digest or hashlib.sha256(content.encode()).hexdigest()
    cur = conn.execute(
        'INSERT INTO versions(article_id,created,digest,content,file_digest,baseline,note) VALUES(?,?,?,?,?,?,?)',
        (article_id, created or time.time(), digest, content, file_digest, int(baseline), note))
    return int(cur.lastrowid)


def latest_version(conn: sqlite3.Connection, article_id: str) -> dict | None:
    return db.row(conn, 'SELECT * FROM versions WHERE article_id=? ORDER BY id DESC LIMIT 1', (article_id,))


def check_hours(conn: sqlite3.Connection, article: dict) -> int | None:
    """Re-check interval for an article or attachment; None when every column is paused."""
    return conn.execute(
        '''SELECT MIN(s.article_hours) FROM sources s WHERE s.enabled=1 AND s.configured=1 AND s.id IN (
             SELECT source_id FROM entries WHERE article_id=:id
             UNION SELECT e.source_id FROM links l JOIN entries e ON e.article_id=l.parent_id WHERE l.attachment_id=:id)''',
        {'id': article['id']}).fetchone()[0]


def version_text(title: str, subtitle: str, body: str) -> str:
    """What is compared between checks: title, subtitle and body."""
    head = [title] + ([subtitle] if subtitle and subtitle != title else [])
    return '\n'.join(head) + '\n\n' + body


def backoff(failures: int, base: float, cap: float) -> float:
    return min(cap, base * (2 ** max(0, failures - 1)))


# --- column lists -------------------------------------------------------------------------

def due_sources(now: float | None = None) -> list[str]:
    with db.tx() as conn:
        return [r['id'] for r in conn.execute(
            'SELECT id FROM sources WHERE configured=1 AND enabled=1 AND next_check<=? ORDER BY next_check',
            (now or time.time(),))]


def check_source(source_id: str, *, force_full: bool = False) -> dict:
    started = time.time()
    with db.tx() as conn:
        src = db.row(conn, 'SELECT * FROM sources WHERE id=? AND configured=1', (source_id,))
        if not src:
            return {'skipped': True}
        full = bool(force_full or src['full_requested'] or not src['initialized'] or not src['last_full']
                    or started - src['last_full'] >= config.FULL_SCAN_HOURS * 3600)
        conn.execute("UPDATE sources SET state='checking', last_check=? WHERE id=?", (started, source_id))
        run_id = conn.execute("INSERT INTO runs(source_id,mode,started,state) VALUES(?,?,?,'running')",
                              (source_id, 'full' if full else 'quick', started)).lastrowid
        known = {r[0] for r in conn.execute('SELECT external_key FROM entries WHERE source_id=?', (source_id,))}
    try:
        pages = _read_list(src, full, known)
        return _record_list(src, run_id, full, pages, started)
    except Exception as exc:  # noqa: BLE001 - every failure is recorded and retried
        reason = fetch.describe(exc) if not isinstance(exc, site.ParseError) else str(exc)
        log.warning('list check failed for %s: %s', source_id, reason)
        with db.tx() as conn:
            failures = src['fail_count'] + 1
            retry = backoff(failures, src['list_minutes'] * 60, 30 * 60)
            conn.execute("UPDATE sources SET state='error', error=?, fail_count=?, next_check=?, full_requested=? WHERE id=?",
                         (reason, failures, time.time() + retry, int(full), source_id))
            conn.execute("UPDATE runs SET state='error', finished=?, message=? WHERE id=?", (time.time(), reason, run_id))
        return {'error': reason}


def _read_list(src: dict, full: bool, known: set[str]) -> list[site.ListPage]:
    pages: list[site.ListPage] = []
    limit = config.FULL_SCAN_MAX_PAGES if full else config.INCREMENTAL_MAX_PAGES
    for number in range(1, limit + 1):
        page = site.fetch_list_page(src['column_id'], number)
        pages.append(page)
        if number >= page.max_page:
            break
        # A quick check stops at the first page that contains anything already known.
        if not full and any(item.external_key in known for item in page.items):
            break
    return pages


def _record_list(src: dict, run_id: int, full: bool, pages: list[site.ListPage], started: float) -> dict:
    now = time.time()
    items = [item for page in pages for item in page.items]
    reported = pages[0].total if pages else 0
    notes: list[str] = []
    with db.tx() as conn:
        existing_entries = conn.execute('SELECT COUNT(*) FROM entries WHERE source_id=?', (src['id'],)).fetchone()[0]
        if not items and existing_entries:
            raise site.ParseError('原站列表返回为空，已保留全部历史数据，等待下次复核')
        added = 0
        for item in items:
            added += _upsert_item(conn, src, item, now)
        if full:
            if len(pages) >= config.FULL_SCAN_MAX_PAGES and pages[-1].max_page > len(pages):
                notes.append(f'达到 {config.FULL_SCAN_MAX_PAGES} 页上限，更早的条目未读取')
            if len(items) != reported:
                notes.append(f'原站报告 {reported} 条，读取到 {len(items)} 条')
        skipped = sum(p.skipped for p in pages)
        if skipped:
            notes.append(f'{skipped} 条记录地址异常，已跳过')
        mode = '完整核对' if full else '快速检查'
        message = f'{mode}：读取 {len(pages)} 页 {len(items)} 条，新增 {added} 篇' + ('；' + '；'.join(notes) if notes else '')
        conn.execute(
            '''UPDATE sources SET state='ok', error='', fail_count=0, initialized=1, reported_total=?,
                 last_success=?, next_check=?, full_requested=0, last_full=CASE WHEN ? THEN ? ELSE last_full END
               WHERE id=?''',
            (reported, now, now + src['list_minutes'] * 60, int(full), now, src['id']))
        conn.execute("UPDATE runs SET state='ok', finished=?, pages=?, rows=?, added=?, message=? WHERE id=?",
                     (now, len(pages), len(items), added, message, run_id))
        # Quiet quick checks are only kept for a week.
        conn.execute("DELETE FROM runs WHERE source_id=? AND mode='quick' AND state='ok' AND added=0 AND started<?",
                     (src['id'], now - 7 * 86400))
    if added:
        log.info('%s: %d new article(s)', src['id'], added)
    return {'pages': len(pages), 'rows': len(items), 'added': added, 'full': full}


def _upsert_item(conn: sqlite3.Connection, src: dict, item: site.ListItem, now: float) -> int:
    article = db.row(conn, 'SELECT * FROM articles WHERE url=?', (item.url,))
    fresh = article is None
    if fresh:
        aid = site.article_id(item.url)
        kind = 'attachment' if site.FILE_EXT.search(item.url) else 'article'
        conn.execute(
            '''INSERT INTO articles(id,url,kind,title,subtitle,published,discovered,title_ok,next_check)
               VALUES(?,?,?,?,?,?,?,?,0)''',
            (aid, item.url, kind, item.title, item.subtitle, item.published, now, int(item.title_ok)))
    else:
        aid = article['id']
        updates: dict = {}
        if item.title_ok and (not article['title_ok'] or article['title'] != item.title):
            updates.update(title=item.title, title_ok=1)
        if item.published and item.published != article['published']:
            updates['published'] = item.published
        if item.subtitle and not article['subtitle']:
            updates['subtitle'] = item.subtitle
        if updates:
            conn.execute(f"UPDATE articles SET {', '.join(k + '=?' for k in updates)} WHERE id=?", [*updates.values(), aid])
    conn.execute(
        '''INSERT INTO entries(source_id,external_key,article_id,page,position,raw_title,first_seen,last_seen)
           VALUES(?,?,?,?,?,?,?,?)
           ON CONFLICT(source_id,external_key) DO UPDATE SET article_id=excluded.article_id, page=excluded.page,
             position=excluded.position, raw_title=excluded.raw_title, last_seen=excluded.last_seen''',
        (src['id'], item.external_key, aid, item.page, item.position, item.raw_title, now, now))
    if fresh and src['initialized']:
        add_event(conn, aid, 'new')
        return 1
    return 0


# --- article bodies and attachments ---------------------------------------------------------------

def due_articles(limit: int, now: float | None = None) -> list[str]:
    """Never-checked items first (new discoveries), then the most overdue."""
    with db.tx() as conn:
        return [r['id'] for r in conn.execute(
            f'''SELECT a.id FROM articles a WHERE a.next_check<=? AND {ACTIVE_ARTICLE}
               ORDER BY a.last_check IS NOT NULL, a.next_check LIMIT ?''',
            (now or time.time(), limit))]


# An article (or attachment) is monitored while at least one enabled column lists it.
ACTIVE_ARTICLE = '''(
  EXISTS(SELECT 1 FROM entries e JOIN sources s ON s.id=e.source_id
         WHERE e.article_id=a.id AND s.enabled=1 AND s.configured=1)
  OR EXISTS(SELECT 1 FROM links l JOIN entries e ON e.article_id=l.parent_id JOIN sources s ON s.id=e.source_id
         WHERE l.attachment_id=a.id AND s.enabled=1 AND s.configured=1))'''


def check_article(article_id: str) -> dict:
    with db.tx() as conn:
        article = db.row(conn, 'SELECT * FROM articles WHERE id=?', (article_id,))
    if not article:
        return {'skipped': True}
    try:
        resp = fetch.get(article['url'])
        if article['kind'] == 'attachment' or not resp.is_html:
            return _record_file(article, resp)
        return _record_page(article, site.parse_article(resp.body, resp.url))
    except Exception as exc:  # noqa: BLE001
        reason = fetch.describe(exc) if not isinstance(exc, site.ParseError) else str(exc)
        log.warning('check failed for %s: %s', article['url'], reason)
        with db.tx() as conn:
            hours = check_hours(conn, article) or 24
            failures = article['fail_count'] + 1
            conn.execute('UPDATE articles SET check_error=?, fail_count=?, last_check=?, next_check=? WHERE id=?',
                         (reason, failures, time.time(), time.time() + backoff(failures, 600, hours * 3600), article['id']))
        return {'error': reason}


def _finish_check(conn: sqlite3.Connection, article: dict) -> None:
    hours = check_hours(conn, article) or 24
    now = time.time()
    conn.execute("UPDATE articles SET check_error='', fail_count=0, last_check=?, next_check=? WHERE id=?",
                 (now, now + hours * 3600, article['id']))


def _record_page(article: dict, page: site.ArticlePage) -> dict:
    result = {'changed': False, 'attachments_added': 0}
    with db.tx() as conn:
        article = db.row(conn, 'SELECT * FROM articles WHERE id=?', (article['id'],)) or article
        updates: dict = {}
        if page.title and (page.title != article['title'] or not article['title_ok']):
            updates.update(title=page.title, title_ok=1)
        if page.subtitle != article['subtitle'] and page.subtitle:
            updates['subtitle'] = page.subtitle
        if page.origin and page.origin != article['origin']:
            updates['origin'] = page.origin
        if page.published and not article['published']:
            updates['published'] = page.published
        if updates:
            conn.execute(f"UPDATE articles SET {', '.join(k + '=?' for k in updates)} WHERE id=?",
                         [*updates.values(), article['id']])
        title = updates.get('title', article['title'])
        content = version_text(title, page.subtitle, page.text)
        digest = hashlib.sha256(content.encode()).hexdigest()
        previous = latest_version(conn, article['id'])
        if previous is None:
            add_version(conn, article['id'], content, baseline=True, note='首次保存')
        elif previous['digest'] != digest:
            if article['rebase']:
                add_version(conn, article['id'], content, baseline=True, note='提取规则更新后重建基线，不计为修订')
            else:
                vid = add_version(conn, article['id'], content, baseline=False)
                add_event(conn, article['id'], 'changed', version_id=vid,
                          summary=diffing.summary(previous['content'], content))
                result['changed'] = True
        conn.execute('UPDATE articles SET rebase=0 WHERE id=?', (article['id'],))
        baselined = previous is not None and not article['rebase']
        for url, name in page.attachments:
            result['attachments_added'] += _link_attachment(conn, article['id'], url, name, announce=baselined)
        _finish_check(conn, article)
    return result


def _link_attachment(conn: sqlite3.Connection, parent_id: str, url: str, name: str, *, announce: bool) -> int:
    now = time.time()
    child = db.row(conn, 'SELECT id FROM articles WHERE url=?', (url,))
    if child:
        child_id = child['id']
    else:
        child_id = site.article_id(url)
        conn.execute("INSERT INTO articles(id,url,kind,title,discovered,next_check) VALUES(?,?,'attachment',?,?,0)",
                     (child_id, url, name or url.rsplit('/', 1)[-1], now))
    if child_id == parent_id:
        return 0
    linked = conn.execute('INSERT OR IGNORE INTO links(parent_id,attachment_id,first_seen) VALUES(?,?,?)',
                          (parent_id, child_id, now)).rowcount
    if linked and announce:
        add_event(conn, parent_id, 'attachment_new', attachment_id=child_id, summary=name)
    return linked


def _record_file(article: dict, resp: fetch.Response) -> dict:
    if resp.is_html:
        raise fetch.FetchError('附件地址返回的是网页，没有取得文件')
    digest = files.save(resp.body)
    text = files.describe(resp.body, digest, resp.content_type)
    with db.tx() as conn:
        conn.execute('INSERT OR IGNORE INTO files(digest,bytes,content_type,created) VALUES(?,?,?,?)',
                     (digest, len(resp.body), resp.content_type[:120], time.time()))
        previous = latest_version(conn, article['id'])
        changed = False
        if previous is None or previous['file_digest'] is None:
            add_version(conn, article['id'], text, baseline=True, file_digest=digest,
                        note='首次保存' if previous is None else '补存文件，作为新基线')
        elif previous['file_digest'] != digest:
            vid = add_version(conn, article['id'], text, baseline=False, file_digest=digest,
                              note='文件字节变化；不一定代表政策内容变化')
            summary = diffing.summary(previous['content'], text)
            parents = [r[0] for r in conn.execute('SELECT parent_id FROM links WHERE attachment_id=?', (article['id'],))]
            for parent in parents or [article['id']]:
                if parent == article['id']:
                    add_event(conn, parent, 'changed', version_id=vid, summary=summary)
                else:
                    add_event(conn, parent, 'attachment_changed', attachment_id=article['id'], version_id=vid, summary=summary)
            changed = True
        _finish_check(conn, article)
    return {'changed': changed}


# --- manual triggers ---------------------------------------------------------------------------

def request_source(source_id: str, full: bool) -> bool:
    with db.tx() as conn:
        return bool(conn.execute(
            'UPDATE sources SET next_check=0, full_requested=MAX(full_requested,?) WHERE id=? AND configured=1',
            (int(full), source_id)).rowcount)


def request_article(article_id: str) -> bool:
    with db.tx() as conn:
        ids = [article_id] + [r[0] for r in conn.execute('SELECT attachment_id FROM links WHERE parent_id=?', (article_id,))]
        return bool(conn.execute(f"UPDATE articles SET next_check=0 WHERE id IN ({','.join('?' * len(ids))})", ids).rowcount)
