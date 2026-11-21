import time
from fastapi import APIRouter, Depends, HTTPException, Request, Query
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select, update, insert, delete, exists, or_, func
from backend import auth
from backend.storage import tables as t, insert_ignore
from backend.wechat_login import WeChatLogin


class LoginInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    code: str = Field(min_length=1, max_length=256)
    invitation: str = Field(default='', max_length=128)


class PreferenceInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    source_ids: list[str] = Field(default_factory=list, max_length=5)
    keywords: list[str] = Field(default_factory=list, max_length=10)
    daily_time: str = Field(default='18:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    quiet_start: str = Field(default='22:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    quiet_end: str = Field(default='08:00', pattern=r'^([01]\d|2[0-3]):[0-5]\d$')
    priority_alerts: bool = True


class FavoriteInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    saved: bool


def router(engine, settings, member, admin, ready, scoped, provider=None):
    api = APIRouter(prefix='/api/v1')
    provider = provider or WeChatLogin(settings)

    def personal(principal=Depends(member)):
        if principal.user_id is None:
            raise HTTPException(403, '个人功能需要微信成员登录')
        return principal

    @api.get('/client-config')
    def config():
        return {'appid': settings.wechat_appid, 'login_configured': bool(settings.wechat_secret),
                'invitation_required': True, 'wechat_notifications_enabled': False}

    @api.post('/auth/wechat', dependencies=[Depends(ready)])
    def login(body: LoginInput, request: Request):
        return auth.login(engine, settings, provider, body.code, body.invitation,
                          request.client.host if request.client else 'unknown')

    @api.post('/auth/logout')
    def logout(principal=Depends(personal)):
        with engine.begin() as conn:
            conn.execute(update(t['sessions']).where(t['sessions'].c.token_hash == principal.session_hash).values(revoked=1))
        return {'ok': True}

    @api.get('/me')
    def me(principal=Depends(personal)):
        with engine.connect() as conn:
            user = conn.execute(select(t['users'].c.id, t['users'].c.name, t['users'].c.role)
                .where(t['users'].c.id == principal.user_id)).mappings().one()
        return dict(user)

    @api.post('/admin/invitations')
    def invitation(principal=Depends(admin)):
        with engine.begin() as conn:
            token = auth.issue_invitation(conn, role='member', created_by=principal.user_id)
        return {'invitation': token, 'expires_in': 86400, 'uses': 1}

    @api.get('/me/preferences')
    def preferences(principal=Depends(personal)):
        with engine.connect() as conn:
            config = conn.scalar(select(t['preferences'].c.config).where(t['preferences'].c.user_id == principal.user_id))
        return config or PreferenceInput().model_dump()

    @api.put('/me/preferences')
    def save_preferences(body: PreferenceInput, principal=Depends(personal)):
        config = body.model_dump()
        if any(not key.strip() or len(key) > 100 for key in config['keywords']):
            raise HTTPException(422, '关键词应为 1–100 个字符')
        with engine.begin() as conn:
            valid = set(conn.scalars(select(t['sources'].c.id).where(t['sources'].c.in_scope == 1)))
            if not set(config['source_ids']) <= valid:
                raise HTTPException(422, '关注来源不在当前范围')
            values = dict(user_id=principal.user_id, config=config, updated=time.time())
            insert_ignore(conn, t['preferences'], values, ['user_id'])
            conn.execute(update(t['preferences']).where(t['preferences'].c.user_id == principal.user_id).values(**values))
        return {'ok': True, 'wechat_notifications_enabled': False}

    def event_scope():
        return t['events'].c.article_id.in_(select(t['article_sources'].c.article_id)
            .join(t['sources'], t['sources'].c.id == t['article_sources'].c.source_id)
            .where(t['sources'].c.in_scope == 1))

    @api.get('/me/events')
    def events(unread: bool = True, page: int = Query(1, ge=1), principal=Depends(personal)):
        e, state, a = t['events'], t['user_event_states'], t['articles']
        where = [event_scope()]
        if unread:
            where.append(~exists(select(state.c.event_id).where(state.c.user_id == principal.user_id,
                state.c.event_id == e.c.id, state.c.read_at.is_not(None))))
        with engine.connect() as conn:
            rows = conn.execute(select(e, a.c.title).join(a, a.c.id == e.c.article_id)
                .where(*where).order_by(e.c.created.desc(), e.c.id).limit(20).offset((page - 1) * 20)).mappings().all()
            total = conn.scalar(select(func.count()).select_from(e).where(*where))
        return {'items': [dict(r) for r in rows], 'total': total, 'page': page}

    @api.post('/articles/{aid}/read')
    def read(aid: str, principal=Depends(personal)):
        with engine.begin() as conn:
            scoped(conn, aid)
            events = conn.scalars(select(t['events'].c.id).where(or_(t['events'].c.article_id == aid,
                t['events'].c.article_id.in_(select(t['article_attachments'].c.attachment_id)
                    .where(t['article_attachments'].c.parent_id == aid)))))
            for eid in events:
                values = dict(user_id=principal.user_id, event_id=eid, read_at=time.time())
                insert_ignore(conn, t['user_event_states'], values, ['user_id', 'event_id'])
                conn.execute(update(t['user_event_states']).where(t['user_event_states'].c.user_id == principal.user_id,
                    t['user_event_states'].c.event_id == eid).values(read_at=values['read_at']))
        return {'ok': True}

    @api.put('/articles/{aid}/favorite')
    def favorite(aid: str, body: FavoriteInput, principal=Depends(personal)):
        with engine.begin() as conn:
            scoped(conn, aid)
            if body.saved:
                insert_ignore(conn, t['favorites'], dict(user_id=principal.user_id, article_id=aid, created=time.time()), ['user_id', 'article_id'])
            else:
                conn.execute(delete(t['favorites']).where(t['favorites'].c.user_id == principal.user_id, t['favorites'].c.article_id == aid))
        return {'saved': body.saved}

    return api
