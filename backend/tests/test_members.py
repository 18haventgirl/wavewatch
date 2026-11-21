from pathlib import Path
import tempfile
import time
import unittest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import select, update, insert, func
from backend import auth, catalog
from backend.api import create_app
from backend.settings import Settings
from backend.storage import make_engine, migrate, tables as t


class FakeWeChat:
    def exchange(self, code):
        return code.split(':')[0]


class MemberTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.engine = make_engine('sqlite:///' + str(Path(self.folder.name) / 'members.sqlite3'))
        migrate(self.engine)
        with self.engine.begin() as conn:
            catalog.seed(conn)
            self.aid, _ = catalog.save_article(conn, 'cn-policy-laws', dict(
                url='https://exportcontrol.mofcom.gov.cn/member.html', title='成员测试'), True)
        self.settings = Settings('sqlite://', 'a' * 32)
        self.client = TestClient(create_app(self.settings, self.engine, FakeWeChat()))
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None, None, None)
        self.engine.dispose()
        self.folder.cleanup()

    def invite(self, role='member'):
        with self.engine.begin() as conn:
            return auth.issue_invitation(conn, role=role)

    def login(self, identity, invitation='', suffix='1'):
        return self.client.post('/api/v1/auth/wechat', json={'code': identity + ':' + suffix, 'invitation': invitation})

    @staticmethod
    def header(response):
        return {'Authorization': 'Bearer ' + response.json()['token']}

    def test_unknown_user_requires_invitation_and_client_cannot_claim_openid(self):
        self.assertEqual(self.login('outsider').status_code, 403)
        r = self.client.post('/api/v1/auth/wechat', json={'code': 'fake', 'openid': 'admin'})
        self.assertEqual(r.status_code, 422)
        self.assertEqual(self.client.get('/api/v1/articles').status_code, 401)

    def test_invitation_single_use_and_login_without_invite_after_binding(self):
        invite = self.invite()
        first = self.login('one', invite)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(self.login('two', invite).status_code, 403)
        self.assertEqual(self.login('one', suffix='2').status_code, 200)
        self.assertNotIn('openid', first.text)
        self.assertNotIn('session_key', first.text)
        with self.engine.connect() as conn:
            hashes = list(conn.scalars(select(t['sessions'].c.token_hash)))
        self.assertNotIn(first.json()['token'], hashes)

    def test_login_code_replay_and_expired_invitation_rejected(self):
        invite = self.invite()
        with self.engine.begin() as conn:
            conn.execute(update(t['invitations']).values(expires=time.time() - 1))
        self.assertEqual(self.login('one', invite).status_code, 403)
        self.assertEqual(self.login('one', invite).status_code, 409)

    def test_sessions_expire_revoke_and_disabled_members_are_denied(self):
        result = self.login('one', self.invite())
        header = self.header(result)
        self.assertEqual(self.client.get('/api/v1/me', headers=header).status_code, 200)
        self.client.post('/api/v1/auth/logout', headers=header)
        self.assertEqual(self.client.get('/api/v1/articles', headers=header).status_code, 401)
        second = self.login('one', suffix='2')
        with self.engine.begin() as conn:
            conn.execute(update(t['sessions']).values(expires=0))
        self.assertEqual(self.client.get('/api/v1/articles', headers=self.header(second)).status_code, 401)
        third = self.login('one', suffix='3')
        with self.engine.begin() as conn:
            conn.execute(update(t['users']).values(active=0))
        self.assertEqual(self.client.get('/api/v1/articles', headers=self.header(third)).status_code, 401)

    def test_member_cannot_issue_admin_invites_or_access_jobs(self):
        member = self.header(self.login('one', self.invite()))
        self.assertEqual(self.client.post('/api/v1/admin/invitations', headers=member).status_code, 403)
        self.assertEqual(self.client.get('/api/v1/jobs', headers=member).status_code, 403)
        admin = self.header(self.login('owner', self.invite('admin')))
        invite = self.client.post('/api/v1/admin/invitations', headers=admin)
        self.assertEqual(invite.status_code, 200)
        enrolled = self.login('two', invite.json()['invitation'])
        self.assertEqual(enrolled.json()['user']['role'], 'member')

    def test_read_states_and_preferences_are_personal(self):
        first = self.header(self.login('one', self.invite()))
        second = self.header(self.login('two', self.invite()))
        with self.engine.begin() as conn:
            conn.execute(insert(t['events']).values(id='new-event', article_id=self.aid, kind='new', created=time.time(), unread=1))
        self.client.post('/api/v1/articles/' + self.aid + '/read', headers=first)
        self.assertEqual(self.client.get('/api/v1/me/events', headers=first).json()['total'], 0)
        self.assertEqual(self.client.get('/api/v1/me/events', headers=second).json()['total'], 1)
        self.client.put('/api/v1/me/preferences', headers=first, json={'daily_time': '09:00'})
        self.assertEqual(self.client.get('/api/v1/me/preferences', headers=second).json()['daily_time'], '18:00')
        self.assertEqual(self.client.put('/api/v1/me/preferences', headers=first, json={'daily_time': '25:00'}).status_code, 422)
        self.assertEqual(self.client.put('/api/v1/me/preferences', headers=first, json={'source_ids':['foreign']} ).status_code, 422)

    def test_new_member_baselines_historical_events(self):
        with self.engine.begin() as conn:
            conn.execute(insert(t['events']).values(id='historical', article_id=self.aid, kind='changed', created=1, unread=1))
        member = self.header(self.login('new', self.invite()))
        self.assertEqual(self.client.get('/api/v1/me/events', headers=member).json()['total'], 0)
        with self.engine.connect() as conn:
            self.assertEqual(conn.scalar(select(t['events'].c.unread)), 1)

    def test_owner_binding_preserves_existing_identity_and_read_state(self):
        with self.engine.begin() as conn:
            conn.execute(insert(t['users']).values(id='legacy-owner', name='原拥有者', role='admin', active=1, created=1))
            invite = auth.issue_invitation(conn, 'admin', target_user='legacy-owner')
        result = self.login('owner', invite)
        self.assertEqual(result.json()['user']['id'], 'legacy-owner')

    def test_missing_secret_is_explicit_and_config_does_not_expose_secrets(self):
        client = TestClient(create_app(self.settings, self.engine))
        r = client.post('/api/v1/auth/wechat', json={'code':'real-code'})
        self.assertEqual(r.status_code, 503)
        config = client.get('/api/v1/client-config').json()
        self.assertEqual(config['appid'], 'wxf4607c24eac40b2b')
        self.assertFalse(config['login_configured'])
        self.assertNotIn('secret', config)

    def test_rate_limit_rejects_excessive_code_exchange(self):
        for n in range(30):
            self.login('outsider', suffix=str(n))
        self.assertEqual(self.login('outsider', suffix='31').status_code, 429)
