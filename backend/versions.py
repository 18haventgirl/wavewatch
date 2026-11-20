import hashlib
import time
from sqlalchemy import select, insert
from backend.storage import tables as t, insert_ignore


def add_version(conn, aid, stamp, content, baseline=False):
    a, v = t['articles'], t['versions']
    # The article lock serializes different kinds of writes to a shared article.
    conn.execute(select(a.c.id).where(a.c.id == aid).with_for_update()).scalar_one()
    existing = conn.execute(select(v.c.id).where(v.c.article_id == aid, v.c.stamp == stamp)).scalar()
    if existing:
        return existing, False
    digest = hashlib.sha256(content.encode()).hexdigest()
    previous = conn.execute(select(v.c.id, v.c.digest).where(v.c.article_id == aid)
                            .order_by(v.c.id.desc()).limit(1)).mappings().first()
    if previous and previous['digest'] == digest:
        return previous['id'], False
    vid = conn.execute(insert(v).values(article_id=aid, stamp=stamp, content=content,
                                        digest=digest, created=time.time()).returning(v.c.id)).scalar_one()
    if previous and not baseline:
        event_id = aid + ':version:' + hashlib.sha256(stamp.encode()).hexdigest()[:40]
        insert_ignore(conn, t['events'], dict(id=event_id, article_id=aid, kind='changed',
                                             created=time.time(), version_id=vid), ['id'])
    return vid, True
