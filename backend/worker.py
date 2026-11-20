import logging
import threading
import time
from sqlalchemy import select, update, insert
from app import collectors
from backend import queue
from backend.catalog import save_article
from backend.storage import tables as t

log = logging.getLogger(__name__)


def discover(engine, job):
    sid = job['payload']['source_id']
    with engine.connect() as conn:
        source = conn.execute(select(t['sources']).where(t['sources'].c.id == sid)).mappings().first()
    if not source or not source['in_scope'] or source['paused']:
        with engine.begin() as conn:
            queue.finish(conn, job)
        return
    started = time.time()
    records, coverage, pages = collectors.discover(source['config'])
    with engine.begin() as conn:
        # No network calls in the commit transaction. Lease fencing rolls all writes back.
        current = conn.execute(select(t['sources']).where(t['sources'].c.id == sid).with_for_update()).mappings().one()
        if current['paused'] or not current['in_scope']:
            queue.finish(conn, job)
            return
        new = sum(int(save_article(conn, sid, item, baseline=not current['initialized'])[1]) for item in records)
        run_id = conn.execute(insert(t['runs']).values(source_id=sid, started=started,
            finished=time.time(), state='success', count=len(records),
            message=f'解析 {len(records)} 条，新增 {new} 条；{coverage}',
            details={'pages': len(pages), 'valid_items': len(records),
                     'reported_total': pages[0]['reported_total'] if pages else None})
            .returning(t['runs'].c.id)).scalar_one()
        for page in pages:
            conn.execute(insert(t['crawl_pages']).values(run_id=run_id, source_id=sid, **page))
        conn.execute(update(t['sources']).where(t['sources'].c.id == sid).values(
            initialized=1, state='discovered', error='', last_check=started,
            last_success=time.time(), coverage=coverage))
        queue.finish(conn, job)


def run_once(engine):
    job = queue.claim(engine)
    if not job:
        return False
    done = threading.Event()

    def heartbeat():
        while not done.wait(30):
            try:
                if not queue.renew(engine, job):
                    return
            except Exception:
                log.exception('Lease renewal failed')
                return

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    try:
        if job['kind'] != 'discover_source':
            raise ValueError('不支持的任务类型')
        discover(engine, job)
    except Exception as exc:
        # Do not persist URLs/headers from transport errors that may carry credentials.
        reason = '采集失败：' + type(exc).__name__
        log.warning('Job %s failed: %s', job['id'], type(exc).__name__)
        def record_failure(conn):
            if job['kind'] == 'discover_source':
                conn.execute(update(t['sources']).where(t['sources'].c.id == job['payload']['source_id'])
                             .values(state='error', error=reason, last_check=time.time()))
        queue.fail(engine, job, reason, on_failure=record_failure)
    finally:
        done.set()
        thread.join(timeout=2)
    return True


def serve(engine):
    try:
        while True:
            if not run_once(engine):
                time.sleep(2)
    except KeyboardInterrupt:
        pass
