import time
import unittest

from fastapi.testclient import TestClient

from app import db, monitor
from app.main import app
from tests.helpers import DataTestCase, article_html, row

LAWS = 'cn-policy-laws'


class ApiTest(DataTestCase):
    def setUp(self):
        super().setUp()
        app.state.no_workers = True
        self.client = TestClient(app)
        self.client.__enter__()
        self.site.set_list(13, [row(1), row(2)])
        self.site.set_page('/article/zcfg/1.html', article_html('出口管制法', ['第一条'], [('/f/a.pdf', '附件A')]))
        self.site.set_page('/article/zcfg/2.html', article_html('两用物项清单', ['第一条']))
        self.site.set_file('/f/a.pdf', b'%PDF-1.4 a')
        monitor.check_source(LAWS)
        for _ in range(2):
            for aid in monitor.due_articles(10, now=time.time() + 1):
                monitor.check_article(aid)
        self.site.set_page('/article/zcfg/1.html', article_html('出口管制法', ['第一条（修订）'], [('/f/a.pdf', '附件A')]))
        self.law = self.q("SELECT id FROM articles WHERE url LIKE '%/1.html'")[0]['id']
        monitor.check_article(self.law)

    def tearDown(self):
        self.client.__exit__(None, None, None)
        super().tearDown()

    def test_overview(self):
        data = self.client.get('/api/overview').json()
        self.assertEqual(data['stats']['articles'], 2)
        self.assertEqual(data['stats']['unread'], 1)
        self.assertEqual(len(data['sources']), 5)
        self.assertEqual(data['recent'][0]['kind'], 'changed')
        self.assertFalse(data['email']['ready'])

    def test_article_list_filters_and_search(self):
        all_items = self.client.get('/api/articles').json()
        self.assertEqual(all_items['total'], 2)
        self.assertEqual(self.client.get('/api/articles', params={'q': '两用'}).json()['total'], 1)
        changed = self.client.get('/api/articles', params={'status': 'changed'}).json()
        self.assertEqual([i['id'] for i in changed['items']], [self.law])
        self.assertEqual(changed['items'][0]['columns'][0]['name'], '法律')
        official = self.client.get('/api/articles', params={'source': LAWS, 'sort': 'official'}).json()
        self.assertEqual(official['items'][0]['title'], '出口管制法')
        self.assertEqual(self.client.get('/api/articles', params={'group': 'news'}).json()['total'], 0)

    def test_detail_compare_and_download(self):
        detail = self.client.get(f'/api/articles/{self.law}').json()
        self.assertEqual(len(detail['versions']), 2)
        self.assertIn('第一条（修订）', detail['content'])
        self.assertEqual(len(detail['attachments']), 1)
        diff = self.client.get(f'/api/articles/{self.law}/compare').json()
        self.assertEqual(diff['stats'], {'added': 1, 'removed': 1})
        self.assertTrue(any(r['type'] == 'changed' for r in diff['rows']))
        digest = detail['attachments'][0]['file_digest']
        resp = self.client.get(f'/api/files/{digest}')
        self.assertEqual(resp.content, b'%PDF-1.4 a')
        self.assertIn('.pdf', resp.headers['content-disposition'])
        self.assertEqual(self.client.get('/api/files/' + '0' * 64).status_code, 404)
        self.assertEqual(self.client.get('/api/files/..%2f..%2fx').status_code, 404)

    def test_read_state(self):
        events = self.client.get('/api/events', params={'unread': True}).json()
        self.assertEqual(events['total'], 1)
        self.client.post('/api/events/read', json={'articles': [self.law]})
        self.assertEqual(self.client.get('/api/events', params={'unread': True}).json()['total'], 0)
        self.client.post('/api/events/read', json={'ids': [events['items'][0]['id']], 'read': False})
        self.assertEqual(self.client.get('/api/overview').json()['stats']['unread'], 1)
        self.client.post('/api/events/read', json={'all': True})
        self.assertEqual(self.client.get('/api/overview').json()['stats']['unread'], 0)

    def test_source_settings_are_validated(self):
        resp = self.client.patch(f'/api/sources/{LAWS}', json={'list_minutes': 2, 'notify': 'digest'})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual((resp.json()['list_minutes'], resp.json()['notify']), (2, 'digest'))
        self.assertEqual(self.client.patch(f'/api/sources/{LAWS}', json={'list_minutes': 0}).status_code, 422)
        self.assertEqual(self.client.patch(f'/api/sources/{LAWS}', json={'notify': 'sms'}).status_code, 422)
        self.assertEqual(self.client.patch('/api/sources/nope', json={'enabled': False}).status_code, 404)
        self.client.post(f'/api/sources/{LAWS}/check', json={'full': True})
        src = self.q('SELECT * FROM sources WHERE id=?', (LAWS,))[0]
        self.assertEqual((src['next_check'], src['full_requested']), (0, 1))

    def test_email_settings_never_return_password(self):
        bad = self.client.put('/api/email', json={'recipients': ['not-an-email']})
        self.assertEqual(bad.status_code, 422)
        incomplete = self.client.put('/api/email', json={'enabled': True})
        self.assertEqual(incomplete.status_code, 400)
        ok = self.client.put('/api/email', json={'host': 'smtp.qq.com', 'port': 465, 'username': 'a@qq.com',
                                                 'password': 'secret-code', 'recipients': ['a@qq.com'], 'enabled': True})
        self.assertEqual(ok.status_code, 200)
        self.assertNotIn('secret-code', ok.text)
        self.assertTrue(ok.json()['password_set'])
        again = self.client.put('/api/email', json={'sender_name': '我的观澜'})
        self.assertTrue(again.json()['password_set'])   # blank password keeps the saved one

    def test_runs_and_health(self):
        runs = self.client.get('/api/runs').json()
        self.assertGreaterEqual(runs['total'], 1)
        self.assertIn('完整核对', runs['items'][0]['message'])
        self.assertIn('workers', self.client.get('/api/health').json())

    def test_requests_from_other_hosts_or_origins_are_rejected(self):
        self.assertEqual(self.client.get('/api/overview', headers={'host': 'evil.example'}).status_code, 403)
        resp = self.client.post('/api/check', headers={'origin': 'http://evil.example'})
        self.assertEqual(resp.status_code, 403)


if __name__ == '__main__':
    unittest.main()
