"""Background workers.

Three independent loops so that a slow attachment download never delays the
next column check:

* lists   – column list checks (default every 5 minutes per column);
* content – article body / attachment checks, new discoveries first;
* mail    – instant / digest / alert e-mails and delivery retries.
"""
from __future__ import annotations

import logging
import threading
import time
import traceback

from . import db, monitor, notify, power

log = logging.getLogger('wavewatch.worker')

stop = threading.Event()
wake_lists = threading.Event()
wake_content = threading.Event()
wake_mail = threading.Event()

status: dict[str, dict] = {
    'lists': {'task': '', 'beat': None, 'error': ''},
    'content': {'task': '', 'beat': None, 'error': ''},
    'mail': {'task': '', 'beat': None, 'error': ''},
}
_threads: list[threading.Thread] = []


def _beat(name: str, task: str = '') -> None:
    status[name]['beat'] = time.time()
    status[name]['task'] = task


def _guard(name: str, fn) -> None:
    """Run one unit of work; a bug in one item must never kill the loop."""
    try:
        fn()
        status[name]['error'] = ''
    except Exception as exc:  # noqa: BLE001
        status[name]['error'] = str(exc)[:300]
        log.error('worker %s failed:\n%s', name, traceback.format_exc())
        stop.wait(5)


def _next_source_wait() -> float:
    with db.tx() as conn:
        due = conn.execute('SELECT MIN(next_check) FROM sources WHERE configured=1 AND enabled=1').fetchone()[0]
    return 30.0 if due is None else max(0.5, min(30.0, due - time.time()))


def lists_loop() -> None:
    while not stop.is_set():
        _beat('lists')

        def work() -> None:
            for source_id in monitor.due_sources():
                if stop.is_set():
                    return
                _beat('lists', source_id)
                monitor.check_source(source_id)
                wake_mail.set()
                wake_content.set()
        _guard('lists', work)
        _beat('lists')
        wake_lists.wait(_next_source_wait())
        wake_lists.clear()


def content_loop() -> None:
    while not stop.is_set():
        _beat('content')
        found: list[str] = []

        def work() -> None:
            found.extend(monitor.due_articles(limit=5))
            for article_id in found:
                if stop.is_set():
                    return
                _beat('content', article_id)
                monitor.check_article(article_id)
            if found:
                # A pending "new article" mail may have been waiting for this body.
                wake_mail.set()
        _guard('content', work)
        _beat('content')
        if not found:
            wake_content.wait(10)
            wake_content.clear()


def mail_loop() -> None:
    while not stop.is_set():
        _beat('mail', 'routing')

        def work() -> None:
            notify.queue_alerts()
            notify.queue_instant()
            notify.queue_digest()
            _beat('mail', 'sending')
            notify.deliver()
        _guard('mail', work)
        _beat('mail')
        wake_mail.wait(15)
        wake_mail.clear()


def power_loop() -> None:
    """Apply the "prevent automatic sleep" option; the state belongs to this thread."""
    applied = None
    while not stop.is_set():
        try:
            with db.tx() as conn:
                wanted = bool(db.get_setting(conn, 'keep_awake', True))
            if wanted != applied:
                power.keep_awake(wanted)
                applied = wanted
        except Exception:  # noqa: BLE001
            log.exception('power setting failed')
        stop.wait(30)
    power.keep_awake(False)


def start() -> None:
    stop.clear()
    for name, target in (('lists', lists_loop), ('content', content_loop), ('mail', mail_loop), ('power', power_loop)):
        thread = threading.Thread(target=target, name=f'wavewatch-{name}', daemon=True)
        thread.start()
        _threads.append(thread)
    log.info('workers started')


def shutdown(timeout: float = 5) -> None:
    stop.set()
    for event in (wake_lists, wake_content, wake_mail):
        event.set()
    for thread in _threads:
        thread.join(timeout)
    _threads.clear()


def healthy(max_age: float = 120) -> bool:
    now = time.time()
    return all(s['beat'] and now - s['beat'] < max_age for s in status.values())
