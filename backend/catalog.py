import hashlib
import json
import time
from sqlalchemy import select, update, insert
from app import collectors
from backend.storage import tables as t, insert_ignore, ROOT


def seed(conn):
    insert_ignore(conn, t['countries'], {'code': 'CN', 'name': '中国'}, ['code'])
    insert_ignore(conn, t['publishers'], dict(id='cn-exportcontrol', country_code='CN', name='中国出口管制信息网', homepage='https://exportcontrol.mofcom.gov.cn/'), ['id'])
    insert_ignore(conn, t['data_scopes'], dict(id='china-exportcontrol', country_code='CN', publisher_id='cn-exportcontrol', name='中国出口管制信息监测', created=time.time()), ['id'])
    configs = json.loads((ROOT / 'config' / 'sources.json').read_text(encoding='utf-8'))
    for position, config in enumerate(configs):
        parent = dict(id=config['parent_id'], publisher_id=config['publisher_id'], name=config['parent_name'], position=0 if config['role'] == 'primary' else 100)
        insert_ignore(conn, t['categories'], parent, ['id'])
        category = dict(id=config['category_id'], publisher_id=config['publisher_id'], parent_id=config['parent_id'], name=config['name'], external_code=str(config['column_id']), position=position)
        insert_ignore(conn, t['categories'], category, ['id'])
        conn.execute(update(t['categories']).where(t['categories'].c.id == category['id']).values(**category))
        values = dict(id=config['id'], config=config, publisher_id=config['publisher_id'],
                      category_id=config['category_id'], scope_id='china-exportcontrol',
                      name=config['name'], in_scope=1)
        insert_ignore(conn, t['sources'], values, ['id'])
        conn.execute(update(t['sources']).where(t['sources'].c.id == config['id']).values(**values))


def save_article(conn, sid, item, baseline):
    a, m, se = t['articles'], t['article_sources'], t['source_entries']
    now = time.time()
    existing = conn.execute(select(a).where(a.c.url == item['url'])).mappings().first()
    aid = existing['id'] if existing else hashlib.sha256(item['url'].encode()).hexdigest()[:24]
    fresh = existing is None
    subtitle = item.get('description', '')
    if subtitle.startswith('列表标题不可读'):
        subtitle = ''
    if fresh:
        conn.execute(insert(a).values(id=aid, origin_source_id=sid, url=item['url'],
            title=item['title'], published=item.get('published'), subtitle=subtitle,
            discovered=now, kind=item.get('kind', 'article'), parent_id=item.get('parent_id')))
        if not baseline:
            insert_ignore(conn, t['events'], dict(id=aid + ':new', article_id=aid,
                kind='attachment_added' if item.get('kind') == 'attachment' else 'new', created=now), ['id'])
    else:
        values = {'title': existing['title'] if collectors.bad_title(item['title']) else item['title']}
        if item.get('published'):
            values['published'] = item['published']
        if not collectors.bad_title(item['title']):
            values['subtitle'] = subtitle
        conn.execute(update(a).where(a.c.id == aid).values(**values))
    membership = dict(article_id=aid, source_id=sid, first_seen=now, last_seen=now,
                      external_key=item.get('external_id'), source_page=item.get('source_page'))
    insert_ignore(conn, m, membership, ['article_id', 'source_id'])
    conn.execute(update(m).where(m.c.article_id == aid, m.c.source_id == sid)
                 .values(last_seen=now, external_key=item.get('external_id'), source_page=item.get('source_page')))
    if item.get('external_id'):
        entry = dict(source_id=sid, external_key=item['external_id'], article_id=aid,
                     source_page=item.get('source_page'), source_position=item.get('source_position'),
                     raw_title=item.get('raw_title', item['title']), first_seen=now, last_seen=now)
        insert_ignore(conn, se, entry, ['source_id', 'external_key'])
        entry.pop('first_seen')
        conn.execute(update(se).where(se.c.source_id == sid, se.c.external_key == item['external_id']).values(**entry))
    return aid, fresh
