from dataclasses import dataclass
import hashlib
import hmac
import secrets
import time
import uuid
from fastapi import HTTPException
from sqlalchemy import select, insert, update, literal, text
from sqlalchemy.exc import IntegrityError
from backend.storage import tables as t, insert_ignore


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()


@dataclass(frozen=True)
class Principal:
    user_id: str | None
    role: str
    session_hash: str | None = None


def authorize(engine, settings, token):
    if settings.admin_token and len(settings.admin_token) >= 32 and hmac.compare_digest(token.encode(), settings.admin_token.encode()):
        return Principal(None, 'admin')
    with engine.connect() as conn:
        session, user = t['sessions'], t['users']
        row = conn.execute(select(session.c.token_hash, user.c.id, user.c.role).join(user, user.c.id == session.c.user_id)
            .where(session.c.token_hash == digest(token), session.c.revoked == 0,
                   session.c.expires > time.time(), user.c.active == 1)).mappings().first()
    if not row:
        raise HTTPException(401, '登录状态已失效，请重新登录', headers={'WWW-Authenticate': 'Bearer'})
    return Principal(row['id'], row['role'], row['token_hash'])


def issue_invitation(conn, role='member', target_user=None, created_by=None, seconds=86400):
    if role not in ('admin', 'member'):
        raise ValueError('Invalid invitation role')
    if target_user:
        user = conn.execute(select(t['users']).where(t['users'].c.id == target_user).with_for_update()).mappings().first()
        if not user or user['role'] != role or not user['active']:
            raise ValueError('Target user role does not match invitation')
    token = 'invite_' + secrets.token_urlsafe(24)
    conn.execute(insert(t['invitations']).values(token_hash=digest(token), role=role,
        target_user_id=target_user, created_by=created_by, created=time.time(), expires=time.time() + seconds, revoked=0))
    return token


def reserve_login(engine, appid, code, remote):
    now = time.time()
    window = int(now // 60)
    key = digest('wechat-login:' + remote + ':' + str(window))
    with engine.begin() as conn:
        insert_ignore(conn, t['auth_buckets'], dict(id=key, window=window * 60, count=0), ['id'])
        admitted = conn.execute(update(t['auth_buckets']).where(t['auth_buckets'].c.id == key,
            t['auth_buckets'].c.count < 30).values(count=t['auth_buckets'].c.count + 1))
        if admitted.rowcount != 1:
            raise HTTPException(429, '登录请求过于频繁，请稍后再试')
        added = insert_ignore(conn, t['login_codes'], dict(code_hash=digest(appid + ':' + code), created=now),
                              ['code_hash'], returning=t['login_codes'].c.code_hash).scalar_one_or_none()
        if added is None:
            raise HTTPException(409, '此登录凭证已使用，请重新登录')


def login(engine, settings, provider, code, invite, remote):
    # A transient exchange error consumes the local attempt: wx.login must generate
    # a fresh code instead of blindly retrying one whose remote result is unknown.
    reserve_login(engine, settings.wechat_appid, code, remote)
    openid = provider.exchange(code)
    if not isinstance(openid, str) or not 1 <= len(openid) <= 128:
        raise HTTPException(502, '微信身份验证未完成')
    now = time.time()
    token = 'gl_' + secrets.token_urlsafe(32)
    try:
        with engine.begin() as conn:
            if conn.dialect.name == 'postgresql':
                lock = int.from_bytes(hashlib.sha256((settings.wechat_appid + ':' + openid).encode()).digest()[:8], 'big', signed=True)
                conn.execute(text('SELECT pg_advisory_xact_lock(:key)'), {'key': lock})
            identity = conn.execute(select(t['wechat_identities']).where(
                t['wechat_identities'].c.appid == settings.wechat_appid, t['wechat_identities'].c.openid == openid)
                .with_for_update()).mappings().first()
            if identity:
                uid = identity['user_id']
            else:
                invitation = conn.execute(select(t['invitations']).where(
                    t['invitations'].c.token_hash == digest(invite or ''), t['invitations'].c.expires > now,
                    t['invitations'].c.used_at.is_(None), t['invitations'].c.revoked == 0).with_for_update()).mappings().first()
                if not invitation:
                    raise HTTPException(403, '需要有效的一次性邀请码')
                uid = invitation['target_user_id'] or uuid.uuid4().hex
                if invitation['target_user_id']:
                    conn.execute(select(t['users'].c.id).where(t['users'].c.id == uid).with_for_update()).scalar_one()
                    bound = conn.scalar(select(t['wechat_identities'].c.user_id).where(
                        t['wechat_identities'].c.user_id == uid, t['wechat_identities'].c.appid == settings.wechat_appid).limit(1))
                    if bound:
                        raise HTTPException(409, '该成员已经绑定微信身份')
                else:
                    conn.execute(insert(t['users']).values(id=uid, name='微信成员', role=invitation['role'], active=1, created=now))
                    # Joining establishes a personal baseline; historical events are not
                    # presented as newly published or pushed to a newly invited member.
                    conn.execute(insert(t['user_event_states']).from_select(['user_id', 'event_id', 'read_at'],
                        select(literal(uid), t['events'].c.id, literal(now))))
                conn.execute(insert(t['wechat_identities']).values(appid=settings.wechat_appid, openid=openid, user_id=uid, created=now))
                conn.execute(update(t['invitations']).where(t['invitations'].c.token_hash == invitation['token_hash'])
                    .values(used_by=uid, used_at=now))
            user = conn.execute(select(t['users']).where(t['users'].c.id == uid).with_for_update()).mappings().one()
            if not user['active']:
                raise HTTPException(403, '该成员已停用')
            expires = now + settings.session_seconds
            conn.execute(insert(t['sessions']).values(token_hash=digest(token), user_id=uid,
                                                     created=now, expires=expires, revoked=0))
            return {'token': token, 'expires_at': expires,
                    'user': {'id': uid, 'name': user['name'], 'role': user['role']}}
    except IntegrityError:
        raise HTTPException(409, '身份绑定发生并发冲突，请重新登录') from None
