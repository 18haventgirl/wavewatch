import json
import smtplib
import time
import unittest
from datetime import datetime

from app import config, db, monitor, notify, secret
from tests.helpers import DataTestCase, article_html, row

LAWS, NEWS = 'cn-policy-laws', 'cn-news-domestic'


class Outbox:
    def __init__(self):
        self.sent: list[dict] = []
        self.error: Exception | None = None

    def __call__(self, settings, subject, text_body, html_body, recipients):
        if self.error:
            raise self.error
        self.sent.append({'subject': subject, 'text': text_body, 'html': html_body, 'to': recipients})


class NotifyTest(DataTestCase):
    def setUp(self):
        super().setUp()
        self.outbox = Outbox()
        self._send = notify.send
        notify.send = self.outbox
        # Baseline for one core and one news column.
        self.site.set_list(13, [row(1)])
        self.site.set_list(1, [row(100)])
        self.site.set_page('/article/zcfg/1.html', article_html('公告 1', ['原文']))
        monitor.check_source(LAWS)
        monitor.check_source(NEWS)

    def tearDown(self):
        notify.send = self._send
        super().tearDown()

    def enable(self, **extra):
        with db.tx() as conn:
            notify.save(conn, {'enabled': True, 'host': 'smtp.example.com', 'username': 'me@example.com',
                               'password': 'app-code', 'recipients': ['me@example.com'], **extra})

    def add_core(self, n: int):
        self.site.set_list(13, [row(n), row(1)])
        self.site.set_page(f'/article/zcfg/{n}.html', article_html(f'公告 {n}', ['新规定内容']))
        monitor.check_source(LAWS)

    def test_events_before_email_was_enabled_are_never_sent(self):
        self.add_core(2)
        self.enable()
        self.assertIsNone(notify.queue_instant(now=time.time() + 3600))

    def test_instant_waits_for_merge_window_then_groups(self):
        self.enable(merge_minutes=2)
        self.add_core(2)
        self.add_core(3)
        for aid in monitor.due_articles(10, now=time.time() + 1):
            monitor.check_article(aid)
        self.assertIsNone(notify.queue_instant())                       # too early
        email_id = notify.queue_instant(now=time.time() + 180)
        self.assertIsNotNone(email_id)
        self.assertIsNone(notify.queue_instant(now=time.time() + 400))  # nothing left
        self.assertEqual(notify.deliver(), 1)
        mail = self.outbox.sent[0]
        self.assertIn('2 条核心更新', mail['subject'])
        self.assertIn('公告 3', mail['text'])
        self.assertIn(f'{config.LOCAL_URL}/#/article/', mail['text'])
        self.assertEqual(self.one("SELECT COUNT(*) FROM emails WHERE state='sent'"), 1)

    def test_new_article_waits_briefly_for_its_body(self):
        self.enable(merge_minutes=0)
        self.add_core(2)
        self.assertIsNone(notify.queue_instant(now=time.time() + 60))   # body not fetched yet
        self.assertIsNotNone(notify.queue_instant(now=time.time() + 700))  # gives up waiting after 10 min

    def test_revision_email_contains_changed_lines(self):
        self.enable(merge_minutes=0)
        self.site.set_page('/article/zcfg/1.html', article_html('公告 1', ['修改后的原文']))
        aid = self.q('SELECT id FROM articles')[0]['id']
        monitor.check_article(aid)   # baseline
        monitor.check_article(aid)   # no change
        self.site.set_page('/article/zcfg/1.html', article_html('公告 1', ['再次修改的原文']))
        monitor.check_article(aid)
        notify.queue_instant(now=time.time() + 1)
        notify.deliver()
        mail = self.outbox.sent[0]
        self.assertIn('正文修订', mail['subject'])
        self.assertIn('+ 再次修改的原文', mail['text'])
        self.assertIn('- 修改后的原文', mail['text'])

    def test_news_goes_to_daily_digest_only(self):
        self.enable(digest_time='18:00')
        self.site.set_list(1, [row(101), row(100)])
        monitor.check_source(NEWS)
        self.assertIsNone(notify.queue_instant(now=time.time() + 3600))
        with db.tx() as conn:
            db.set_setting(conn, 'digest_last', time.time() - 1)
        tomorrow = time.time() + 86400 + 60
        email_id = notify.queue_digest(now=tomorrow)
        self.assertIsNotNone(email_id)
        self.assertIsNone(notify.queue_digest(now=tomorrow + 60))  # once per slot
        notify.deliver(now=tomorrow)
        self.assertIn('观澜日报', self.outbox.sent[0]['subject'])
        self.assertIn('公告 101', self.outbox.sent[0]['text'])

    def test_empty_digest_is_skipped_by_default(self):
        self.enable()
        self.assertIsNone(notify.queue_digest(now=time.time() + 86400 + 60))

    def test_digest_slot_is_beijing_time(self):
        settings = {**notify.DEFAULTS, 'digest_time': '18:00'}
        now = datetime(2026, 11, 23, 9, 0, tzinfo=config.BEIJING).timestamp()
        slot = datetime.fromtimestamp(notify.digest_due_at(settings, now), config.BEIJING)
        self.assertEqual((slot.day, slot.hour), (22, 18))

    def test_alert_after_repeated_failures_and_recovery(self):
        self.enable(alert_failures=2)
        from app import fetch
        self.site.fail['list'] = fetch.FetchError('连接原站超时，稍后自动重试')
        monitor.check_source(LAWS)
        self.assertEqual(notify.queue_alerts(), [])
        monitor.check_source(LAWS)
        self.assertEqual(len(notify.queue_alerts()), 1)
        self.assertEqual(notify.queue_alerts(), [])    # only once per incident
        del self.site.fail['list']
        monitor.check_source(LAWS)
        self.assertEqual(len(notify.queue_alerts()), 1)  # recovery notice
        notify.deliver()
        self.assertEqual([m['subject'][-4:] for m in self.outbox.sent], ['检查失败', '恢复正常'])

    def test_transient_failure_retries_and_auth_failure_stops(self):
        self.enable(merge_minutes=0)
        self.add_core(2)
        notify.queue_instant(now=time.time() + 700)
        self.outbox.error = OSError('timed out')
        notify.deliver()
        mail = self.q('SELECT * FROM emails')[0]
        self.assertEqual((mail['state'], mail['attempts']), ('pending', 1))
        self.assertIn('超时', mail['last_error'])
        self.outbox.error = smtplib.SMTPAuthenticationError(535, b'auth failed')
        notify.deliver(now=time.time() + 3600)
        mail = self.q('SELECT * FROM emails')[0]
        self.assertEqual(mail['state'], 'failed')
        self.assertIn('授权码', mail['last_error'])

    def test_password_is_sealed_and_never_exposed(self):
        self.enable()
        with db.tx() as conn:
            stored = notify.load(conn)
        self.assertNotIn('app-code', json.dumps(stored))
        self.assertEqual(secret.unseal(stored['password']), 'app-code')
        public = notify.public(stored)
        self.assertNotIn('password', public)
        self.assertTrue(public['password_set'])

    def test_off_columns_are_never_emailed(self):
        with db.tx() as conn:
            conn.execute("UPDATE sources SET notify='off'")
        self.enable(merge_minutes=0)
        self.add_core(2)
        self.assertIsNone(notify.queue_instant(now=time.time() + 700))
        self.assertEqual(self.q('SELECT route FROM events')[0]['route'], 'off')


if __name__ == '__main__':
    unittest.main()
