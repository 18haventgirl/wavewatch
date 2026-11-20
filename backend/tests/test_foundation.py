import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from sqlalchemy import select, update, insert, func, text
from fastapi.testclient import TestClient
from backend.storage import make_engine, migrate, tables as t
from backend import queue, catalog, scheduler, worker
from backend.api import create_app
from backend.settings import Settings


class FoundationTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.engine = make_engine('sqlite:///' + str(Path(self.folder.name) / 'server.sqlite3'))
        migrate(self.engine)
        with self.engine.begin() as conn:
            catalog.seed(conn)

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def test_migrations_repeat_without_resetting_preferences(self):
        with self.engine.begin() as conn:
            conn.execute(update(t['sources']).values(hours=12, paused=1))
        migrate(self.engine)
        with self.engine.begin() as conn:
            catalog.seed(conn)
            rows = list(conn.execute(select(t['sources'])).mappings())
            self.assertEqual(len(rows), 5)
            self.assertTrue(all(r['hours'] == 12 and r['paused'] == 1 for r in rows))

    def test_scheduler_restart_deduplicates_and_paused_sources_skipped(self):
        with self.engine.begin() as conn:
            conn.execute(update(t['sources']).where(t['sources'].c.id == 'cn-policy-laws').values(paused=1))
        count = scheduler.tick(self.engine, 100)
        with self.engine.connect() as conn:
            diagnostic = list(conn.execute(select(t['sources'].c.id, t['sources'].c.next_check,
                t['sources'].c.paused, t['sources'].c.in_scope)).mappings())
        self.assertEqual(count, 4, str(diagnostic))
        self.assertEqual(scheduler.tick(self.engine, 101), 0)
        # The overdue queue prevents creating another job even after the next interval.
        self.assertEqual(scheduler.tick(self.engine, 100000), 0)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['jobs'])), 4)

    def test_expired_lease_reclaimed_and_stale_writer_fenced(self):
        now = time.time()
        with self.engine.begin() as conn:
            queue.enqueue(conn, 'one', 'discover_source', {}, due=now)
        old = queue.claim(self.engine, now, 10)
        self.assertIsNone(queue.claim(self.engine, now + 1))
        new = queue.claim(self.engine, now + 11)
        self.assertNotEqual(old['lease_token'], new['lease_token'])
        with self.assertRaises(RuntimeError):
            with self.engine.begin() as conn:
                conn.execute(update(t['sources']).values(hours=99))
                queue.finish(conn, old)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(t['sources'].c.hours).limit(1)), 6)
        with self.engine.begin() as conn:
            queue.finish(conn, new)

    def test_failed_tasks_back_off_and_stop(self):
        with self.engine.begin() as conn:
            queue.enqueue(conn, 'fail', 'unknown', {})
        for attempt in range(1, 6):
            job = queue.claim(self.engine)
            self.assertEqual(job['attempts'], attempt)
            queue.fail(self.engine, job, 'network')
            with self.engine.begin() as conn:
                row = conn.execute(select(t['jobs'])).mappings().one()
                self.assertEqual(row['state'], 'dead' if attempt == 5 else 'ready')
                self.assertGreater(row['due'], time.time())
                conn.execute(update(t['jobs']).values(due=time.time() - 1))
        self.assertIsNone(queue.claim(self.engine))

    def test_discovery_baseline_and_same_url_categories(self):
        source = 'cn-policy-laws'
        item = dict(url='https://exportcontrol.mofcom.gov.cn/test.html', title='测试公告',
                    description='（通过日期）', external_id='a', source_position=1, source_page=1)
        with self.engine.begin() as conn:
            queue.enqueue(conn, 'baseline', 'discover_source', {'source_id': source})
        with patch.object(worker.collectors, 'discover', return_value=([item], '覆盖一页', [])):
            worker.run_once(self.engine)
        with self.engine.begin() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['events'])), 0)
            aid, fresh = catalog.save_article(conn, 'cn-policy-regulations', item, True)
            self.assertFalse(fresh)
            self.assertEqual(conn.scalar(select(t['articles'].c.subtitle)), '（通过日期）')
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['article_sources'])), 2)
            queue.enqueue(conn, 'new', 'discover_source', {'source_id': source})
        new_item = item | {'url': 'https://exportcontrol.mofcom.gov.cn/new.html', 'external_id': 'b'}
        with patch.object(worker.collectors, 'discover', return_value=([item, new_item], '覆盖', [])):
            worker.run_once(self.engine)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['events'])), 1)

    def test_api_requires_auth_and_does_not_start_workers(self):
        token = 'test-token-' + 'x' * 32
        app = create_app(Settings('sqlite://', token), self.engine)
        with patch('app.service.start') as legacy_start, TestClient(app) as client:
            self.assertEqual(client.get('/api/v1/sources').status_code, 401)
            self.assertEqual(client.get('/health/ready').status_code, 200)
            response = client.get('/api/v1/sources', headers={'Authorization': 'Bearer ' + token})
            self.assertEqual(len(response.json()['items']), 5)
            self.assertEqual(client.post('/api/check').status_code, 404)
            legacy_start.assert_not_called()
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['jobs'])), 0)

    def test_official_order_and_subtitle_are_exposed(self):
        with self.engine.begin() as conn:
            for n in [2, 1]:
                catalog.save_article(conn, 'cn-policy-laws', dict(
                    url=f'https://exportcontrol.mofcom.gov.cn/{n}.html', title=f'公告{n}',
                    description=f'通过说明{n}', external_id=str(n), source_position=n), True)
        token = 'x' * 32
        with TestClient(create_app(Settings('sqlite://', token), self.engine)) as client:
            result = client.get('/api/v1/articles?category=cn-domestic-laws&sort=official',
                                headers={'Authorization': 'Bearer ' + token}).json()
            self.assertEqual([r['title'] for r in result['items']], ['公告1', '公告2'])
            self.assertEqual(result['items'][0]['subtitle'], '通过说明1')


if __name__ == '__main__':
    unittest.main()
