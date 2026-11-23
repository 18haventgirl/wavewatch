import time
import unittest

from app import config, db, fetch, monitor
from tests.helpers import DataTestCase, article_html, row

LAWS = 'cn-policy-laws'          # column 13, core
NEWS = 'cn-news-domestic'        # column 1, news


def run_content(limit: int = 100) -> list[dict]:
    return [monitor.check_article(a) for a in monitor.due_articles(limit, now=time.time() + 1)]


class BaselineTest(DataTestCase):
    def test_first_scan_builds_baseline_without_events(self):
        self.site.set_list(13, [row(i) for i in range(1, 26)])
        for i in range(1, 26):
            self.site.set_page(f'/article/zcfg/{i}.html', article_html(f'公告 {i}', ['正文']))
        result = monitor.check_source(LAWS)
        self.assertTrue(result['full'])
        self.assertEqual(result['rows'], 25)
        self.assertEqual(result['pages'], 2)
        run_content()
        self.assertEqual(self.one('SELECT COUNT(*) FROM articles'), 25)
        self.assertEqual(self.one('SELECT COUNT(*) FROM versions WHERE baseline=1'), 25)
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)
        src = self.q('SELECT * FROM sources WHERE id=?', (LAWS,))[0]
        self.assertEqual(src['initialized'], 1)
        self.assertEqual(src['state'], 'ok')
        self.assertGreater(src['next_check'], time.time() + 60)


class NewArticleTest(DataTestCase):
    def setUp(self):
        super().setUp()
        self.site.set_list(13, [row(1), row(2)])
        self.site.set_page('/article/zcfg/1.html', article_html('公告 1', ['第一条']))
        self.site.set_page('/article/zcfg/2.html', article_html('公告 2', ['第一条']))
        monitor.check_source(LAWS)
        run_content()

    def test_quick_check_finds_new_article_and_emits_one_event(self):
        self.site.set_list(13, [row(3), row(1), row(2)])
        self.site.set_page('/article/zcfg/3.html', article_html('公告 3', ['新规定']))
        self.site.calls.clear()
        result = monitor.check_source(LAWS)
        self.assertFalse(result['full'])
        self.assertEqual(result['added'], 1)
        self.assertEqual(self.site.calls, ['list:13:1'])   # one request per quick check
        events = self.q('SELECT * FROM events')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]['kind'], 'new')
        self.assertEqual(events[0]['route'], 'instant')
        # repeated checks do not duplicate
        monitor.check_source(LAWS)
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 1)
        # the new article's body is fetched first, as a silent baseline
        due = monitor.due_articles(10, now=time.time() + 1)
        self.assertEqual(due[0], self.q("SELECT id FROM articles WHERE url LIKE '%/3.html'")[0]['id'])
        run_content()
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 1)

    def test_news_column_routes_to_digest(self):
        self.site.set_list(1, [row(50)])
        self.site.set_page('/article/zcfg/50.html', article_html('资讯', ['内容']))
        monitor.check_source(NEWS)                       # baseline
        self.site.set_list(1, [row(51), row(50)])
        monitor.check_source(NEWS)
        self.assertEqual(self.q('SELECT route FROM events')[0]['route'], 'digest')

    def test_article_in_core_and_news_uses_strongest_route(self):
        self.site.set_list(1, [row(9, path='/article/zcfg/1.html')])
        monitor.check_source(NEWS)
        with db.tx() as conn:
            self.assertEqual(monitor.route_for(conn, self.q("SELECT id FROM articles WHERE url LIKE '%/1.html'")[0]['id']), 'instant')

    def test_incremental_reads_more_pages_only_while_everything_is_new(self):
        rows = [row(i) for i in range(100, 145)] + [row(1), row(2)]
        self.site.set_list(13, rows)
        self.site.calls.clear()
        result = monitor.check_source(LAWS)
        self.assertEqual(self.site.calls, ['list:13:1', 'list:13:2', 'list:13:3'])
        self.assertEqual(result['added'], 45)


class RevisionTest(DataTestCase):
    def setUp(self):
        super().setUp()
        self.site.set_list(13, [row(1)])
        self.site.set_page('/article/zcfg/1.html', article_html('出口管制法', ['第一条 为了维护国家安全。', '第二条 适用范围。']))
        monitor.check_source(LAWS)
        run_content()
        self.aid = self.q('SELECT id FROM articles')[0]['id']

    def test_body_change_creates_version_and_event(self):
        self.site.set_page('/article/zcfg/1.html', article_html('出口管制法', ['第一条 为了维护国家安全和利益。', '第二条 适用范围。']))
        monitor.request_article(self.aid)
        run_content()
        events = self.q('SELECT * FROM events')
        self.assertEqual([e['kind'] for e in events], ['changed'])
        self.assertIn('新增 1 行', events[0]['summary'])
        self.assertEqual(self.one('SELECT COUNT(*) FROM versions WHERE article_id=?', (self.aid,)), 2)

    def test_whitespace_and_page_chrome_are_not_revisions(self):
        html = article_html('出口管制法', ['第一条  为了维护国家安全。', '第二条 适用范围。']).replace(
            '免责声明：本站转载……', '免责声明：页脚文字已更新').replace('<nav>导航</nav>', '<nav>新导航</nav>')
        self.site.set_page('/article/zcfg/1.html', html.replace('　　', '\xa0'))
        monitor.request_article(self.aid)
        run_content()
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)
        self.assertEqual(self.one('SELECT COUNT(*) FROM versions'), 1)

    def test_title_change_is_a_revision(self):
        self.site.set_page('/article/zcfg/1.html', article_html('出口管制法（修正）', ['第一条 为了维护国家安全。', '第二条 适用范围。']))
        monitor.request_article(self.aid)
        run_content()
        self.assertEqual(self.one("SELECT COUNT(*) FROM events WHERE kind='changed'"), 1)
        self.assertEqual(self.q('SELECT title FROM articles')[0]['title'], '出口管制法（修正）')

    def test_rebase_flag_rebuilds_baseline_silently(self):
        with db.tx() as conn:
            conn.execute('UPDATE articles SET rebase=1')
        self.site.set_page('/article/zcfg/1.html', article_html('出口管制法', ['完全不同的格式']))
        monitor.request_article(self.aid)
        run_content()
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)
        self.assertEqual(self.one('SELECT rebase FROM articles'), 0)
        self.assertEqual(self.one('SELECT COUNT(*) FROM versions WHERE baseline=1'), 2)

    def test_failed_check_backs_off_and_keeps_data(self):
        self.site.fail['https://exportcontrol.mofcom.gov.cn/article/zcfg/1.html'] = fetch.FetchError('原站返回 HTTP 503')
        monitor.request_article(self.aid)
        run_content()
        art = self.q('SELECT * FROM articles')[0]
        self.assertEqual(art['fail_count'], 1)
        self.assertIn('503', art['check_error'])
        self.assertGreater(art['next_check'], time.time() + 500)
        self.assertEqual(self.one('SELECT COUNT(*) FROM versions'), 1)

    def test_missing_body_area_is_an_error_not_a_revision(self):
        self.site.set_page('/article/zcfg/1.html', '<html><body>Please wait… verify you are human</body></html>')
        monitor.request_article(self.aid)
        run_content()
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)
        self.assertIn('访问验证', self.q('SELECT check_error FROM articles')[0]['check_error'])


class AttachmentTest(DataTestCase):
    def setUp(self):
        super().setUp()
        self.site.set_list(13, [row(1)])
        self.site.set_page('/article/zcfg/1.html', article_html('清单', ['见附件'], [('/upload/a.pdf', '管制清单.pdf')]))
        self.site.set_file('/upload/a.pdf', b'%PDF-1.4 version one')
        monitor.check_source(LAWS)
        run_content()
        run_content()

    def test_attachment_is_linked_and_saved_as_baseline(self):
        att = self.q("SELECT * FROM articles WHERE kind='attachment'")[0]
        self.assertEqual(att['title'], '管制清单.pdf')
        self.assertEqual(self.one('SELECT COUNT(*) FROM links'), 1)
        self.assertEqual(self.one('SELECT COUNT(*) FROM files'), 1)
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)
        digest = self.q('SELECT file_digest FROM versions WHERE article_id=?', (att['id'],))[0]['file_digest']
        self.assertTrue((config.FILES / digest[:2] / digest).is_file())

    def test_file_change_notifies_parent(self):
        self.site.set_file('/upload/a.pdf', b'%PDF-1.4 version two')
        with db.tx() as conn:
            conn.execute('UPDATE articles SET next_check=0')
        run_content()
        events = self.q('SELECT * FROM events')
        self.assertEqual([e['kind'] for e in events], ['attachment_changed'])
        parent = self.q("SELECT id FROM articles WHERE kind='article'")[0]['id']
        self.assertEqual(events[0]['article_id'], parent)

    def test_new_attachment_on_known_article_is_announced(self):
        self.site.set_page('/article/zcfg/1.html', article_html('清单', ['见附件'], [('/upload/a.pdf', '管制清单.pdf'),
                                                                                    ('/upload/b.docx', '说明.docx')]))
        self.site.set_file('/upload/b.docx', b'PK docx', 'application/octet-stream')
        with db.tx() as conn:
            conn.execute("UPDATE articles SET next_check=0 WHERE kind='article'")
        run_content()
        kinds = sorted(e['kind'] for e in self.q('SELECT kind FROM events'))
        self.assertEqual(kinds, ['attachment_new', 'changed'])  # body text gained a line too

    def test_attachment_url_returning_html_is_an_error(self):
        self.site.set_page('/upload/a.pdf', '<html>not found</html>')
        with db.tx() as conn:
            conn.execute("UPDATE articles SET next_check=0 WHERE kind='attachment'")
        run_content()
        self.assertIn('网页', self.q("SELECT check_error FROM articles WHERE kind='attachment'")[0]['check_error'])
        self.assertEqual(self.one('SELECT COUNT(*) FROM events'), 0)


class ListFailureTest(DataTestCase):
    def setUp(self):
        super().setUp()
        self.site.set_list(13, [row(1)])
        monitor.check_source(LAWS)

    def test_network_failure_is_recorded_and_retried_later(self):
        self.site.fail['list'] = fetch.FetchError('连接原站超时，稍后自动重试')
        result = monitor.check_source(LAWS)
        self.assertIn('超时', result['error'])
        src = self.q('SELECT * FROM sources WHERE id=?', (LAWS,))[0]
        self.assertEqual((src['state'], src['fail_count']), ('error', 1))
        self.assertEqual(self.q('SELECT state FROM runs ORDER BY id DESC LIMIT 1')[0]['state'], 'error')
        del self.site.fail['list']
        monitor.check_source(LAWS)
        src = self.q('SELECT * FROM sources WHERE id=?', (LAWS,))[0]
        self.assertEqual((src['state'], src['fail_count'], src['error']), ('ok', 0, ''))

    def test_empty_list_never_wipes_history(self):
        self.site.set_list(13, [])
        result = monitor.check_source(LAWS)
        self.assertIn('为空', result['error'])
        self.assertEqual(self.one('SELECT COUNT(*) FROM entries'), 1)

    def test_bad_titles_are_repaired_from_the_article_page(self):
        self.site.set_list(13, [row(2, title='????????????'), row(1)])
        self.site.set_page('/article/zcfg/2.html', article_html('真实标题', ['正文']))
        monitor.check_source(LAWS)
        art = self.q("SELECT * FROM articles WHERE url LIKE '%/2.html'")[0]
        self.assertEqual((art['title'], art['title_ok']), ('官方文章 · 2', 0))
        run_content()
        art = self.q("SELECT * FROM articles WHERE url LIKE '%/2.html'")[0]
        self.assertEqual((art['title'], art['title_ok']), ('真实标题', 1))

    def test_paused_column_is_not_checked(self):
        with db.tx() as conn:
            conn.execute('UPDATE sources SET enabled=0, next_check=0')
        self.assertEqual(monitor.due_sources(), [])
        self.assertEqual(monitor.due_articles(10, now=time.time() + 10 ** 6), [])


if __name__ == '__main__':
    unittest.main()
