import time
from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select, update, text, exists, case, and_, or_
from backend.storage import tables as t
from backend.queue import enqueue


def tick_monitoring(engine, now=None, limit=32):
    now = time.time() if now is None else now
    a, m, s, state, j = t['articles'], t['article_sources'], t['sources'], t['monitor_states'], t['jobs']
    from backend.monitoring import is_file
    from backend.storage import insert_ignore
    with engine.begin() as conn:
        if conn.dialect.name == 'postgresql' and not conn.scalar(text('SELECT pg_try_advisory_xact_lock(673861013)')):
            return 0
        missing = conn.scalars(select(a.c.id).join(m, m.c.article_id == a.c.id)
            .join(s, m.c.source_id == s.c.id).outerjoin(state, state.c.article_id == a.c.id)
            .where(s.c.in_scope == 1, state.c.article_id.is_(None)).distinct().limit(200)).all()
        for aid in missing:
            insert_ignore(conn, state, {'article_id': aid}, ['article_id'])
        from sqlalchemy import func
        pending_count = conn.scalar(select(func.count()).select_from(j).where(
            j.c.kind.in_(['inspect_article', 'sync_article']), j.c.state.in_(['ready', 'leased'])))
        remaining = min(limit, max(0, 64 - pending_count))
        if not remaining:
            return 0
        pending = exists(select(j.c.id).where(j.c.resource_key == 'article:' + a.c.id,
                                              j.c.state.in_(['ready', 'leased'])))
        file_clause = or_(a.c.kind == 'attachment', *[
            func.lower(a.c.url).like('%.' + ext) for ext in ('pdf', 'doc', 'docx', 'xls', 'xlsx', 'zip')])
        active_due = and_(func.min(s.c.paused) == 0, or_(
            and_(~file_clause, state.c.next_inspect <= now), state.c.next_sync <= now,
            and_(~file_clause, state.c.engine_paused == 1)))
        paused_due = and_(func.min(s.c.paused) == 1, ~file_clause,
                         or_(state.c.engine_paused.is_(None), state.c.engine_paused == 0))
        earliest = case((file_clause, state.c.next_sync),
                        (state.c.next_inspect < state.c.next_sync, state.c.next_inspect), else_=state.c.next_sync)
        rows = conn.execute(select(a.c.id, a.c.kind, a.c.url, state.c.next_inspect,
                state.c.next_sync, state.c.engine_paused, func.min(s.c.paused).label('paused'))
            .join(m, m.c.article_id == a.c.id).join(s, m.c.source_id == s.c.id)
            .join(state, state.c.article_id == a.c.id).where(s.c.in_scope == 1, ~pending)
            .group_by(a.c.id, a.c.kind, a.c.url, state.c.next_inspect, state.c.next_sync, state.c.engine_paused)
            .having(or_(active_due, paused_due))
            .order_by(case((func.min(s.c.paused) == 1, 0), else_=earliest), a.c.id).limit(200)).mappings().all()
        count = 0
        for row in rows:
            if count >= remaining:
                break
            if row['paused']:
                kind, due = 'sync_article', row['next_sync']
                if is_file(row):
                    continue
            elif row['engine_paused'] == 1 and not is_file(row):
                kind, due = 'sync_article', row['next_sync']
            elif not is_file(row) and row['next_inspect'] <= now:
                kind, due = 'inspect_article', row['next_inspect']
            elif row['next_sync'] <= now:
                kind, due = 'sync_article', row['next_sync']
            else:
                continue
            count += enqueue(conn, f"{kind}:{row['id']}:{due}", kind, {'article_id': row['id']},
                             due=now, resource='article:' + row['id'])
        return count


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
    scheduler.add_job(tick_monitoring, 'interval', seconds=15, args=[engine], id='articles',
                      max_instances=1, coalesce=True, misfire_grace_time=60)
    tick(engine)
    tick_monitoring(engine)
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass
