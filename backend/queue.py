"""Durable, fenced leases. PostgreSQL workers use SKIP LOCKED."""
import time
import uuid
import hashlib
from sqlalchemy import select, update, or_, and_, exists, text
from backend.storage import tables, insert_ignore

jobs = tables['jobs']
MAX_ATTEMPTS = 5


def enqueue(conn, key, kind, payload, due=None, resource=None):
    now = time.time()
    result = insert_ignore(conn, jobs, dict(
        id=uuid.uuid4().hex, dedup_key=key, kind=kind, payload=payload,
        resource_key=resource or key, state='ready', due=now if due is None else due,
        created=now, attempts=0, error=''), ['dedup_key'], returning=jobs.c.id)
    return result.scalar_one_or_none() is not None


def claim(engine, now=None, lease_seconds=120):
    now = time.time() if now is None else now
    with engine.begin() as conn:
        conn.execute(update(jobs).where(jobs.c.state == 'leased', jobs.c.lease_until <= now,
                                       jobs.c.attempts >= MAX_ATTEMPTS)
                     .values(state='dead', finished=now, error='任务租约过期且已达尝试上限'))
        other = jobs.alias('other_job')
        available = or_(and_(jobs.c.state == 'ready', jobs.c.due <= now),
                        and_(jobs.c.state == 'leased', jobs.c.lease_until <= now))
        blocked = exists(select(other.c.id).where(
            other.c.resource_key == jobs.c.resource_key, other.c.id != jobs.c.id,
            other.c.state == 'leased', other.c.lease_until > now))
        query = select(jobs).where(available, ~blocked, jobs.c.attempts < MAX_ATTEMPTS).order_by(jobs.c.due, jobs.c.created).limit(1)
        if conn.dialect.name == 'postgresql':
            query = query.with_for_update(skip_locked=True)
        row = conn.execute(query).mappings().first()
        if not row:
            return None
        if conn.dialect.name == 'postgresql':
            # Serialize claims for a resource even when two different jobs were selected.
            lock_id = int.from_bytes(hashlib.sha256(row['resource_key'].encode()).digest()[:8], 'big', signed=True)
            if not conn.scalar(text('SELECT pg_try_advisory_xact_lock(:key)'), {'key': lock_id}):
                return None
            if conn.scalar(select(exists(select(jobs.c.id).where(
                    jobs.c.resource_key == row['resource_key'], jobs.c.id != row['id'],
                    jobs.c.state == 'leased', jobs.c.lease_until > now)))):
                return None
        token = uuid.uuid4().hex
        updated = conn.execute(update(jobs).where(jobs.c.id == row['id'], available)
                               .values(state='leased', lease_token=token,
                                       lease_until=now + lease_seconds, attempts=jobs.c.attempts + 1)
                               .returning(jobs)).mappings().first()
        return dict(updated) if updated else None


def renew(engine, job, lease_seconds=120):
    now = time.time()
    with engine.begin() as conn:
        return conn.execute(update(jobs).where(
            jobs.c.id == job['id'], jobs.c.lease_token == job['lease_token'],
            jobs.c.state == 'leased', jobs.c.lease_until > now)
            .values(lease_until=now + lease_seconds)).rowcount == 1


def assert_lease(conn, job):
    row = conn.execute(select(jobs.c.id).where(
        jobs.c.id == job['id'], jobs.c.lease_token == job['lease_token'],
        jobs.c.state == 'leased', jobs.c.lease_until > time.time()).with_for_update()).first()
    if not row:
        raise RuntimeError('任务租约已失效，本次业务写入回滚')


def finish(conn, job):
    # A stale worker must never commit business writes after another took its lease.
    updated = conn.execute(update(jobs).where(
        jobs.c.id == job['id'], jobs.c.lease_token == job['lease_token'],
        jobs.c.state == 'leased', jobs.c.lease_until > time.time())
        .values(state='done', finished=time.time(), lease_token=None, lease_until=None, error=''))
    if updated.rowcount != 1:
        raise RuntimeError('任务租约已失效，本次业务写入回滚')


def fail(engine, job, reason, on_failure=None):
    now = time.time()
    with engine.begin() as conn:
        result = conn.execute(update(jobs).where(jobs.c.id == job['id'],
            jobs.c.lease_token == job['lease_token'], jobs.c.state == 'leased')
            .values(state='dead' if job['attempts'] >= MAX_ATTEMPTS else 'ready',
                    due=now + min(3600, 30 * 2 ** (job['attempts'] - 1)),
                    lease_token=None, lease_until=None, error=reason[:500]))
        if result.rowcount == 1 and on_failure is not None:
            on_failure(conn)
        return result.rowcount == 1
