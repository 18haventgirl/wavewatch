"""Use a generated disposable schema, never the existing app's schema."""
import concurrent.futures
import os
import uuid
import unittest
from fastapi.testclient import TestClient
from backend.api import create_app
from sqlalchemy import text, select, insert
from sqlalchemy.engine import make_url
from backend.storage import make_engine, migrate, tables as t
from backend import catalog, queue
from backend.import_legacy import import_snapshot
from backend.tests import test_foundation as foundation
from backend.tests import test_import as legacy_import
from backend.tests import test_monitoring as monitoring
from backend.tests import test_members as members


class PostgresMixin:
    def configure_postgres(self):
        self.sqlite_engine = self.engine
        self.admin_engine = make_engine(os.environ['OBS_TEST_DATABASE_URL'])
        self.schema = 'test_' + uuid.uuid4().hex
        with self.admin_engine.begin() as conn:
            conn.execute(text('CREATE SCHEMA "' + self.schema + '"'))
        url = make_url(os.environ['OBS_TEST_DATABASE_URL']).update_query_dict({'options': '-csearch_path=' + self.schema})
        self.engine = make_engine(url)
        migrate(self.engine)

    def cleanup_postgres(self):
        self.engine.dispose()
        with self.admin_engine.begin() as conn:
            # Only this test's literal generated schema is eligible for removal.
            if not self.schema.startswith('test_') or len(self.schema) != 37:
                raise RuntimeError('Invalid test schema')
            conn.execute(text('DROP SCHEMA "' + self.schema + '" CASCADE'))
        self.admin_engine.dispose()
        self.engine = self.sqlite_engine


@unittest.skipUnless(os.environ.get('OBS_TEST_DATABASE_URL'), 'isolated PostgreSQL test URL not configured')
class PostgresFoundationTests(PostgresMixin, foundation.FoundationTests):
    def setUp(self):
        super().setUp()
        self.configure_postgres()
        with self.engine.begin() as conn:
            catalog.seed(conn)

    def tearDown(self):
        self.cleanup_postgres()
        super().tearDown()

    def test_concurrent_claims_do_not_overlap_resources(self):
        with self.engine.begin() as conn:
            queue.enqueue(conn, 'one', 'discover_source', {}, resource='same')
            queue.enqueue(conn, 'two', 'discover_source', {}, resource='same')
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            result = list(pool.map(lambda _: queue.claim(self.engine), range(2)))
        self.assertEqual(sum(r is not None for r in result), 1)


@unittest.skipUnless(os.environ.get('OBS_TEST_DATABASE_URL'), 'isolated PostgreSQL test URL not configured')
class PostgresImportTests(PostgresMixin, legacy_import.ImportTests):
    def setUp(self):
        super().setUp()
        self.configure_postgres()

    def tearDown(self):
        self.cleanup_postgres()
        super().tearDown()

    def test_legacy_ids_leave_sequences_ready_for_new_versions(self):
        import_snapshot(self.engine, self.source, apply=True, target_files=self.root / 'files')
        with self.engine.begin() as conn:
            aid = conn.scalar(select(t['articles'].c.id))
            vid = conn.execute(insert(t['versions']).values(article_id=aid, stamp='3', content='next', digest='x' * 64, created=1).returning(t['versions'].c.id)).scalar_one()
            self.assertEqual(vid, 3)


@unittest.skipUnless(os.environ.get('OBS_TEST_DATABASE_URL'), 'isolated PostgreSQL test URL not configured')
class PostgresMonitoringTests(PostgresMixin, monitoring.MonitoringTests):
    def setUp(self):
        super().setUp()
        self.configure_postgres()
        with self.engine.begin() as conn:
            catalog.seed(conn)

    def tearDown(self):
        self.cleanup_postgres()
        super().tearDown()


@unittest.skipUnless(os.environ.get('OBS_TEST_DATABASE_URL'), 'isolated PostgreSQL test URL not configured')
class PostgresMemberTests(PostgresMixin, members.MemberTests):
    def setUp(self):
        super().setUp()
        self.client.__exit__(None, None, None)
        self.configure_postgres()
        with self.engine.begin() as conn:
            catalog.seed(conn)
            self.aid, _ = catalog.save_article(conn, 'cn-policy-laws', dict(
                url='https://exportcontrol.mofcom.gov.cn/member.html', title='成员测试'), True)
        self.client = TestClient(create_app(self.settings, self.engine, members.FakeWeChat()))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.cleanup_postgres()
        super().tearDown()
