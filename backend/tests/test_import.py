import hashlib
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from sqlalchemy import select, func
from app import db
from backend.storage import make_engine, migrate, tables as t
from backend.import_legacy import import_snapshot


class ImportTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)
        self.source = self.root / 'legacy' / 'observatory.sqlite3'
        with patch.object(db, 'DATA', self.source.parent), patch.object(db, 'DB', self.source):
            db.init()
            with db.connection() as conn:
                aid, _ = db.add_article(conn, 'cn-policy-laws', dict(
                    url='https://exportcontrol.mofcom.gov.cn/legacy.html', title='历史公告',
                    description='（官网说明）', external_id='a', source_position=1), True)
                db.add_version(conn, aid, '1', 'first body')
                db.add_version(conn, aid, '2', 'changed body')
                conn.execute('UPDATE events SET unread=0')
                content = b'test immutable attachment'
                digest = hashlib.sha256(content).hexdigest()
                folder = self.source.parent / 'attachments'
                folder.mkdir()
                (folder / digest).write_bytes(content)
                conn.execute('INSERT INTO file_blobs VALUES(?,?,?)', (digest, str(folder / digest), len(content)))
        self.engine = make_engine('sqlite:///' + str(self.root / 'v2.sqlite3'))
        migrate(self.engine)

    def tearDown(self):
        self.engine.dispose()
        self.folder.cleanup()

    def test_atomic_import_preserves_history_and_owner_read_state(self):
        report = import_snapshot(self.engine, self.source, apply=True, target_files=self.root / 'files')
        self.assertTrue(report['verified'])
        with self.engine.connect() as conn:
            article = conn.execute(select(t['articles'])).mappings().one()
            self.assertEqual(article['subtitle'], '（官网说明）')
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['versions'])), 2)
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['user_event_states'])), 1)
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['jobs'])), 0)
        self.assertEqual(len(list((self.root / 'files' / 'attachments').iterdir())), 1)
        with self.assertRaisesRegex(ValueError, 'must be empty'):
            import_snapshot(self.engine, self.source, apply=True, target_files=self.root / 'files')

    def test_dry_run_writes_nothing_and_missing_blob_fails(self):
        self.assertEqual(import_snapshot(self.engine, self.source)['mode'], 'dry-run')
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(func.count()).select_from(t['sources'])), 0)
        next((self.source.parent / 'attachments').iterdir()).unlink()
        with self.assertRaisesRegex(ValueError, 'Missing or damaged'):
            import_snapshot(self.engine, self.source, apply=True, target_files=self.root / 'files')


if __name__ == '__main__':
    unittest.main()
