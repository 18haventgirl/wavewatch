import hashlib
import sqlite3
import time
import unittest
from pathlib import Path

from app import db, diffing, legacy, monitor, secret, site
from tests.helpers import DataTestCase, article_html, list_body, row

FIXTURES = Path(__file__).parent / 'fixtures'


class SiteParserTest(unittest.TestCase):
    """Real pages saved from exportcontrol.mofcom.gov.cn."""

    def test_text_article(self):
        url = 'https://exportcontrol.mofcom.gov.cn/article/gjdt/202111/327.html'
        page = site.parse_article((FIXTURES / 'article_text.html').read_bytes(), url)
        self.assertEqual(page.title, '2021年1月美国商务部澄清出口管制分类编码1C991的范围')
        self.assertEqual(page.origin, '美国联邦纪事网站')
        self.assertEqual(page.published, '2021-12-30 08:15:41')
        self.assertTrue(page.text.startswith('2021年1月7日'))
        self.assertNotIn('免责声明', page.text)            # site boilerplate is excluded
        self.assertNotIn('var title', page.text)
        self.assertNotIn('\u3000', page.text)

    def test_image_only_article(self):
        url = 'https://exportcontrol.mofcom.gov.cn/article/zcfg/gnzcfg/zcfggzqd/202111/424.html'
        page = site.parse_article((FIXTURES / 'article_images.html').read_bytes(), url)
        self.assertIn('[图片]', page.text)

    def test_attachment_article(self):
        url = 'https://exportcontrol.mofcom.gov.cn/article/zcfg/gnzcfg/zcfggzqd/202611/1339.html'
        page = site.parse_article((FIXTURES / 'article_attachment.html').read_bytes(), url)
        self.assertEqual(len(page.attachments), 1)
        self.assertTrue(page.attachments[0][0].endswith('.pdf'))

    def test_list_parsing(self):
        rows = [row(1), {'id': '2', 'title': '??????????', 'url': '/article/x/2.html', 'publishTimeStr': ''},
                {'id': '3', 'title': '外链', 'url': 'https://example.com/x.html'}]
        page = site.parse_list_page(list_body(rows, total=3), 1, 13)
        self.assertEqual(len(page.items), 2)
        self.assertEqual(page.skipped, 1)
        self.assertFalse(page.items[1].title_ok)
        self.assertIsNone(page.items[1].published)
        with self.assertRaises(site.ParseError):
            site.parse_list_page(b'<html>Just a moment...</html>', 1, 13)
        with self.assertRaises(site.ParseError):
            site.parse_list_page(list_body([], page=2), 1, 13)

    def test_official_url_allowlist(self):
        from app import fetch
        base = 'https://exportcontrol.mofcom.gov.cn/a/b.html'
        self.assertEqual(fetch.official_url(base, '/x.pdf'), 'https://exportcontrol.mofcom.gov.cn/x.pdf')
        self.assertEqual(fetch.official_url(base, 'http://exportcontrol.mofcom.gov.cn/x#frag'),
                         'https://exportcontrol.mofcom.gov.cn/x')
        for bad in ('https://evil.com/x', 'javascript:alert(1)', 'https://user@exportcontrol.mofcom.gov.cn/x', ''):
            self.assertIsNone(fetch.official_url(base, bad))

    def test_diff_rows(self):
        rows = diffing.compare('a\nb\nc', 'a\nB\nc\nd')
        kinds = [r['type'] for r in rows]
        self.assertEqual(kinds, ['same', 'changed', 'same', 'added'])
        self.assertEqual(diffing.summary('a\nb', 'a\nc\nd'), '新增 2 行，删除 1 行')

    def test_secret_roundtrip(self):
        self.assertEqual(secret.unseal(secret.seal('授权码 123')), '授权码 123')
        self.assertEqual(secret.seal(''), '')


LEGACY_SCHEMA = '''
CREATE TABLE sources(id TEXT PRIMARY KEY, in_scope INTEGER, initialized INTEGER, last_success REAL);
CREATE TABLE articles(id TEXT PRIMARY KEY, url TEXT, title TEXT, description TEXT, published TEXT,
  discovered REAL, kind TEXT, watch_id TEXT);
CREATE TABLE article_sources(article_id TEXT, source_id TEXT);
CREATE TABLE source_entries(source_id TEXT, external_key TEXT, article_id TEXT, source_page INTEGER,
  source_position INTEGER, raw_title TEXT, first_seen REAL, last_seen REAL);
CREATE TABLE article_attachments(parent_id TEXT, attachment_id TEXT, first_seen REAL);
CREATE TABLE versions(id INTEGER PRIMARY KEY, article_id TEXT, stamp TEXT, content TEXT, digest TEXT, created REAL);
CREATE TABLE file_versions(version_id INTEGER, blob_digest TEXT);
CREATE TABLE file_blobs(digest TEXT, path TEXT, bytes INTEGER);
CREATE TABLE events(id TEXT, article_id TEXT, kind TEXT, created REAL, unread INTEGER);
PRAGMA user_version=5;
'''


class LegacyImportTest(DataTestCase):
    def build_legacy(self):
        path = self.tmp / 'observatory.sqlite3'
        conn = sqlite3.connect(path)
        conn.executescript(LEGACY_SCHEMA)
        url1 = 'https://exportcontrol.mofcom.gov.cn/article/zcfg/1.html'
        url2 = 'https://exportcontrol.mofcom.gov.cn/article/zcfg/2.html'
        pdf = 'https://exportcontrol.mofcom.gov.cn/f/a.pdf'
        a1, a2, f1 = site.article_id(url1), site.article_id(url2), site.article_id(pdf)
        conn.executemany('INSERT INTO sources VALUES(?,?,?,?)', [('cn-policy-laws', 1, 1, 100.0), ('us-old', 0, 1, 1.0)])
        conn.executemany('INSERT INTO articles VALUES(?,?,?,?,?,?,?,?)', [
            (a1, url1, '公告 1', '', '2026-11-01', 10.0, 'article', 'w1'),
            (a2, url2, '公告 2', '', '2026-11-02', 11.0, 'article', 'w2'),
            (f1, pdf, '附件A', '', None, 12.0, 'attachment', None),
            ('old', 'https://www.bis.gov/x', 'archived', '', None, 1.0, 'article', None)])
        conn.executemany('INSERT INTO article_sources VALUES(?,?)',
                         [(a1, 'cn-policy-laws'), (a2, 'cn-policy-laws'), (f1, 'cn-policy-laws'), ('old', 'us-old')])
        conn.executemany('INSERT INTO source_entries VALUES(?,?,?,?,?,?,?,?)',
                         [('cn-policy-laws', '1', a1, 1, 1, '公告 1', 10, 10), ('cn-policy-laws', '2', a2, 1, 2, '公告 2', 11, 11)])
        conn.execute('INSERT INTO article_attachments VALUES(?,?,?)', (a1, f1, 12))
        conn.executemany('INSERT INTO versions(id,article_id,stamp,content,digest,created) VALUES(?,?,?,?,?,?)', [
            (1, a1, 's', '旧引擎格式正文 1', 'x', 10), (2, a2, 's', '旧引擎格式正文 2', 'y', 11), (3, f1, 'f', 'PDF 文本', 'z', 12)])
        digest = hashlib.sha256(b'%PDF-old').hexdigest()
        (self.tmp / 'attachments').mkdir()
        (self.tmp / 'attachments' / digest).write_bytes(b'%PDF-old')
        conn.execute('INSERT INTO file_versions VALUES(3,?)', (digest,))
        conn.execute('INSERT INTO file_blobs VALUES(?,?,?)', (digest, 'C:\\gone\\' + digest, 8))
        conn.commit()
        conn.close()
        # Engine snapshot for article 1 only ("decoded" by an identity function in this test).
        (self.tmp / 'engine' / 'w1').mkdir(parents=True)
        (self.tmp / 'engine' / 'w1' / '1795144489.html.br').write_text(article_html('公告 1', ['第一条']), encoding='utf-8')
        return a1, a2, f1

    def test_import_preserves_data_and_never_raises_false_revisions(self):
        a1, a2, f1 = self.build_legacy()
        report = legacy.run(decode=lambda b: b)
        self.assertEqual((report['articles'], report['attachments'], report['from_snapshot'], report['rebase']), (2, 1, 1, 1))
        self.assertEqual(self.one('SELECT COUNT(*) FROM articles'), 3)          # archived source skipped
        self.assertEqual(self.one('SELECT COUNT(*) FROM entries'), 2)
        self.assertEqual(self.one('SELECT COUNT(*) FROM links'), 1)
        self.assertEqual(self.one('SELECT COUNT(*) FROM files'), 1)            # found via the attachments folder
        self.assertEqual(self.one('SELECT initialized FROM sources WHERE id=?', ('cn-policy-laws',)), 1)
        with self.assertRaises(RuntimeError):
            legacy.run(decode=lambda b: b)                                         # never twice
        # Live pages identical to the snapshot / old text produce no events.
        self.site.set_page('/article/zcfg/1.html', article_html('公告 1', ['第一条']))
        self.site.set_page('/article/zcfg/2.html', article_html('公告 2', ['新格式正文']))
        self.site.set_file('/f/a.pdf', b'%PDF-old')
        for aid in monitor.due_articles(10, now=time.time() + 7200):
            monitor.check_article(aid)
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)
        self.assertEqual(self.one('SELECT rebase FROM articles WHERE id=?', (a2,)), 0)
        # A real change after import is reported.
        self.site.set_page('/article/zcfg/1.html', article_html('公告 1', ['第一条（修订）']))
        monitor.check_article(a1)
        self.assertEqual(self.one("SELECT COUNT(*) FROM events WHERE kind='changed'"), 1)

    def test_wrong_version_is_refused(self):
        path = self.tmp / 'observatory.sqlite3'
        sqlite3.connect(path).execute('PRAGMA user_version=3').connection.close()
        with self.assertRaises(RuntimeError):
            legacy.run()
        self.assertIsNone(legacy.maybe_import())
        with db.tx() as conn:
            self.assertIn('error', db.get_setting(conn, 'legacy_import'))


if __name__ == '__main__':
    unittest.main()
