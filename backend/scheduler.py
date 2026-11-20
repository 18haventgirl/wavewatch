import time
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select, update, text, exists
from backend.storage import tables as t
from backend.queue import enqueue


def tick(engine, now=None):
    now = time.time() if now is None else now
    s, j = t['sources'], t['jobs']
    with engine.begin() as conn:
        # Transaction-scoped singleton lock; no long-lived lock on an idle connection.
        if conn.dialect.name == 'postgresql' and not conn.scalar(text('SELECT pg_try_advisory_xact_lock(673861011)')):
            return 0
        pending = exists(select(j.c.id).where(j.c.resource_key == 'source:' + s.c.id,
                                              j.c.state.in_(['ready', 'leased'])))
        query = select(s).where(s.c.in_scope == 1, s.c.paused == 0,
                                s.c.next_check <= now, ~pending)
        if conn.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        rows = list(conn.execute(query).mappings())
        count = 0
        for row in rows:
            key = f"source:{row['id']}:{row['next_check']}"
            count += enqueue(conn, key, 'discover_source', {'source_id': row['id']},
                             due=now, resource='source:' + row['id'])
            conn.execute(update(s).where(s.c.id == row['id']).values(next_check=now + row['hours'] * 3600))
        return count


def serve(engine):
    scheduler = BlockingScheduler(timezone='Asia/Shanghai')
    scheduler.add_job(tick, 'interval', seconds=15, args=[engine], id='sources',
                      max_instances=1, coalesce=True, misfire_grace_time=60)
    tick(engine)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
