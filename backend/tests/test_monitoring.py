import hashlib
import io
from pathlib import Path
import tempfile
import time
import unittest
import uuid
from unittest.mock import patch
from fastapi.testclient import TestClient
from sqlalchemy import select, update, insert, func, inspect
from alembic import command
from alembic.config import Config
from backend import catalog, queue, worker, scheduler
from backend.api import create_app
from backend.engine_client import EngineClient
from backend.monitoring import state_for
from backend.settings import Settings
from backend.storage import make_engine, migrate, tables as t, ROOT
from backend.versions import add_version


class FakeEngine:
    def __init__(self, article):
        self.watch = dict(url=article['url'], title=article['title'], paused=False,
                          time_between_check={'hours': 6}, time_between_check_use_default=False,
                          notification_muted=True, include_filters=['.u-art-box'])
        self.history = {}
        self.snapshots = {}
        self.rechecks = 0

    @staticmethod
    def path(wid, suffix=''):
        return 'watch/' + wid + suffix

    def ensure_watch(self, article, hours, paused=False):
        return 'test-watch'

    def api(self, path, method='GET', payload=None):
        if method == 'PUT':
            self.watch.update(payload)
            return None
        if path.endswith('?recheck=1'):
            self.rechecks += 1
            return None
        if path.endswith('/history'):
            return dict(self.history)
        if '/history/' in path:
            return self.snapshots[path.rsplit('/', 1)[1]]
        return dict(self.watch)

    def version(self, stamp, content):
        self.history[str(stamp)] = 'saved'
        self.snapshots[str(stamp)] = content


class MonitoringTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.engine = make_engine('sqlite:///' + str(self.root / 'server.sqlite3'))
        migrate(self.engine)
        with self.engine.begin() as conn:
            catalog.seed(conn)
        self.settings = Settings('sqlite://', 'x' * 32, files_root=self.root)

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def article(self, name='one', sid='cn-policy-laws', kind='article', parent=None):
        with self.engine.begin() as conn:
            aid, _ = catalog.save_article(conn, sid, dict(url=f'https://exportcontrol.mofcom.gov.cn/{name}.html',
                title='官方文章 · ' + name, kind=kind, parent_id=parent), True)
            return dict(conn.execute(select(t['articles']).where(t['articles'].c.id == aid)).mappings().one())

    def run_job(self, article, kind='sync_article', client=None, body=None, ctype='application/pdf'):
        with self.engine.begin() as conn:
            queue.enqueue(conn, uuid.uuid4().hex, kind, {'article_id': article['id']}, resource='article:' + article['id'])
        if body is not None:
            with patch('app.collectors.fetch', return_value=(body, ctype)):
                worker.run_once(self.engine, settings=self.settings, client=client)
        else:
            worker.run_once(self.engine, settings=self.settings, client=client)

    def count(self, name):
        with self.engine.connect() as conn:
            return conn.scalar(select(func.count()).select_from(t[name]))

    def test_titles_and_shared_attachments_preserve_all_relationships(self):
        first = self.article('one')
        second = self.article('two', sid='cn-policy-regulations')
        html = '<script>var title = "核实的官方标题";</script><div class="u-art-box">这是足够长的官方公告正文内容，用来核实文章和附件。<a href="/shared.pdf">附件.pdf</a></div>'.encode()
        self.run_job(first, 'inspect_article', body=html, ctype='text/html')
        self.run_job(second, 'inspect_article', body=html, ctype='text/html')
        self.assertEqual(self.count('article_attachments'), 2)
        self.assertEqual(self.count('articles'), 3)
        self.assertEqual(self.count('events'), 0)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(t['articles'].c.title).where(t['articles'].c.id == first['id'])), '核实的官方标题')
            fileid = conn.scalar(select(t['articles'].c.id).where(t['articles'].c.kind == 'attachment'))
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['article_sources']).where(t['article_sources'].c.article_id == fileid)), 2)

    def test_file_a_a_b_a_preserves_three_versions_and_protected_download(self):
        article = self.article('file', kind='attachment')
        for data in [b'A bytes', b'A bytes', b'B bytes', b'A bytes']:
            self.run_job(article, body=data, ctype='application/octet-stream')
        self.assertEqual(self.count('versions'), 3)
        self.assertEqual(self.count('events'), 2)
        self.assertEqual(self.count('file_blobs'), 2)
        self.assertEqual(self.count('file_versions'), 3)
        with TestClient(create_app(self.settings, self.engine)) as client:
            url = '/api/v1/attachments/' + article['id'] + '/download'
            self.assertEqual(client.get(url).status_code, 401)
            self.assertEqual(client.get(url, headers={'Authorization': 'Bearer ' + self.settings.admin_token}).content, b'A bytes')

    def test_existing_attachment_digest_does_not_alert_on_extraction_notice_change(self):
        article = self.article('file', kind='attachment')
        body = b'same unchanged file'
        digest = hashlib.sha256(body).hexdigest()
        with self.engine.begin() as conn:
            vid, _ = add_version(conn, article['id'], 'legacy', 'old extraction notice')
            conn.execute(insert(t['file_blobs']).values(digest=digest, path='attachments/' + digest, bytes=len(body)))
            conn.execute(insert(t['file_versions']).values(version_id=vid, blob_digest=digest))
        self.run_job(article, body=body, ctype='application/octet-stream')
        self.assertEqual(self.count('versions'), 1)
        self.assertEqual(self.count('events'), 0)

    def test_history_backlog_and_duplicate_snapshots_do_not_starve_new_versions(self):
        article = self.article()
        client = FakeEngine(article)
        for stamp in range(1, 21):
            client.version(stamp, '官方正文内容第一版，足够长用于内容验证。')
        client.version(21, '官方正文内容已经修订为第二版，足够长用于内容验证。')
        self.run_job(article, client=client)
        self.assertEqual(self.count('versions'), 1)
        self.run_job(article, client=client)
        self.run_job(article, client=client)
        self.assertEqual(self.count('versions'), 2)
        self.assertEqual(self.count('events'), 1)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(t['monitor_states'].c.history_cursor)), 21)

    def test_filter_change_rebases_once_and_old_history_is_not_imported(self):
        article = self.article()
        client = FakeEngine(article)
        client.watch['include_filters'] = ['old-filter']
        client.version(1, '旧过滤器正文包含导航以及页面中的很多旧数据。')
        with self.engine.begin() as conn:
            add_version(conn, article['id'], 'legacy', '旧业务库的正文内容，与新提取规则不同。')
        self.run_job(article, client=client)
        self.assertEqual(client.rechecks, 1)
        client.version(2, '新过滤器正文内容，排除导航后建立新的比较基线。')
        self.run_job(article, client=client)
        self.assertEqual(self.count('events'), 0)
        client.version(3, '新过滤器正文内容发生实际修订，应该产生真实变化事件。')
        self.run_job(article, client=client)
        self.run_job(article, client=client)
        self.assertEqual(self.count('versions'), 3)
        self.assertEqual(self.count('events'), 1)

    def test_invalid_body_and_attachment_responses_keep_prior_versions(self):
        article = self.article()
        client = FakeEngine(article)
        client.version(1, '原来的有效正文内容足够长，当前已经确认并归档。')
        self.run_job(article, client=client)
        client.version(2, 'Please wait, verify you are human before continuing')
        self.run_job(article, client=client)
        self.assertEqual(self.count('versions'), 1)
        self.assertEqual(self.count('events'), 0)
        file = self.article('file', kind='attachment')
        self.run_job(file, body=b'<html>access denied</html>', ctype='text/html')
        self.assertEqual(self.count('file_blobs'), 0)
        with self.engine.connect() as conn:
            self.assertTrue(conn.scalar(select(t['monitor_states'].c.sync_error).where(t['monitor_states'].c.article_id == file['id'])))

    def test_pausing_and_resuming_shared_article_controls_engine_once(self):
        article = self.article()
        with self.engine.begin() as conn:
            catalog.save_article(conn, 'cn-policy-regulations', dict(url=article['url'], title=article['title']), True)
            conn.execute(update(t['sources']).where(t['sources'].c.id == 'cn-policy-laws').values(paused=1, hours=1))
            conn.execute(update(t['sources']).where(t['sources'].c.id == 'cn-policy-regulations').values(hours=24))
        client = FakeEngine(article)
        self.run_job(article, client=client)
        self.assertFalse(client.watch['paused'])
        self.assertEqual(client.watch['time_between_check']['hours'], 24)
        with self.engine.begin() as conn:
            conn.execute(update(t['sources']).values(paused=1))
        self.assertEqual(scheduler.tick_monitoring(self.engine), 1)
        worker.run_once(self.engine, self.settings, client)
        self.assertTrue(client.watch['paused'])
        self.assertEqual(scheduler.tick_monitoring(self.engine), 0)
        with self.engine.begin() as conn:
            conn.execute(update(t['sources']).where(t['sources'].c.id == 'cn-policy-regulations').values(paused=0))
        self.assertEqual(scheduler.tick_monitoring(self.engine), 1)
        worker.run_once(self.engine, self.settings, client)
        self.assertFalse(client.watch['paused'])

    def test_scanned_pdf_notice_is_saved_with_original_bytes(self):
        from pypdf import PdfWriter
        buffer = io.BytesIO()
        writer = PdfWriter()
        writer.add_blank_page(width=100, height=100)
        writer.write(buffer)
        article = self.article('pdf', kind='attachment')
        self.run_job(article, body=buffer.getvalue())
        with self.engine.connect() as conn:
            self.assertIn('无可提取文本', conn.scalar(select(t['versions'].c.content)))

    def test_v1_server_migration_preserves_existing_rows(self):
        old = make_engine('sqlite:///' + str(self.root / 'old-server.sqlite3'))
        config = Config()
        config.set_main_option('script_location', str(ROOT / 'backend' / 'migrations'))
        with old.begin() as conn:
            config.attributes['connection'] = conn
            command.upgrade(config, '0001_server')
        self.assertNotIn('monitor_states', inspect(old).get_table_names())
        with old.begin() as conn:
            catalog.seed(conn)
            catalog.save_article(conn, 'cn-policy-laws', dict(url='https://exportcontrol.mofcom.gov.cn/migrate.html', title='迁移保留'), True)
        migrate(old)
        with old.connect() as conn:
            self.assertEqual(conn.scalar(select(t['articles'].c.title)), '迁移保留')
        self.assertIn('monitor_states', inspect(old).get_table_names())
        old.dispose()

    def test_missing_engine_configuration_never_reads_legacy_secrets(self):
        with self.assertRaisesRegex(RuntimeError, 'isolated V2'):
            EngineClient(self.settings)

    def test_recheck_failure_keeps_rebase_marker_for_retry(self):
        article = self.article()
        client = FakeEngine(article)
        client.watch['include_filters'] = ['old-filter']
        client.version(1, '旧的提取规则包含导航，需要调整成文章正文范围。')
        with self.engine.begin() as conn:
            add_version(conn, article['id'], 'legacy', '旧库保存的文章正文，需建立新提取规则基线。')
        api = client.api

        def transient(path, method='GET', payload=None):
            if path.endswith('?recheck=1'):
                raise RuntimeError('temporary engine disconnect')
            return api(path, method, payload)

        with patch.object(client, 'api', side_effect=transient):
            self.run_job(article, client=client)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(t['monitor_states'].c.rebase_after)), 1)
        client.version(2, '新规则下首次提取的正文，作为新的比较基线使用。')
        # Let the persisted failed job retry; no replacement task is needed.
        with self.engine.begin() as conn:
            conn.execute(update(t['jobs']).where(t['jobs'].c.state == 'ready').values(due=0))
        worker.run_once(self.engine, self.settings, client)
        self.assertEqual(self.count('versions'), 2)
        self.assertEqual(self.count('events'), 0)
