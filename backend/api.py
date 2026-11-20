"""Private server foundation. No anonymous data or legacy mutation endpoints."""
from contextlib import asynccontextmanager
import hmac
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy import select, func, or_, literal, text
from backend.settings import Settings
from backend.storage import make_engine, tables as t

bearer = HTTPBearer(auto_error=False)


def create_app(settings=None, engine=None):
    settings = settings or Settings.load()
    engine = engine or make_engine(settings.database_url)

    @asynccontextmanager
    async def lifespan(_app):
        # Deliberately no migration, scheduler, worker, or legacy service.start().
        yield
        engine.dispose()

    app = FastAPI(title='观澜服务器版 · 开发基础接口', lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    def admin(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if len(settings.admin_token) < 32:
            raise HTTPException(503, '尚未配置开发管理令牌')
        if not credentials or not hmac.compare_digest(credentials.credentials, settings.admin_token):
            raise HTTPException(401, '需要身份验证', headers={'WWW-Authenticate': 'Bearer'})

    def ready():
        try:
            with engine.connect() as conn:
                version = conn.scalar(text('SELECT version_num FROM alembic_version'))
                if version != '0001_server':
                    raise ValueError('migration required')
        except Exception:
            raise HTTPException(503, '数据库未就绪') from None

    @app.get('/health/live')
    def live():
        return {'status': 'alive'}

    @app.get('/health/ready')
    def readiness():
        ready()
        return {'status': 'ready', 'edition': 'server-foundation'}

    @app.get('/api/v1/sources', dependencies=[Depends(admin), Depends(ready)])
    def sources():
        s, c = t['sources'], t['categories']
        with engine.connect() as conn:
            rows = conn.execute(select(s, c.c.position).join(c, s.c.category_id == c.c.id)
                                .where(s.c.in_scope == 1).order_by(c.c.position)).mappings()
            return {'items': [dict(r) for r in rows]}

    @app.get('/api/v1/articles', dependencies=[Depends(admin), Depends(ready)])
    def articles(category: str = '', q: str = Query('', max_length=200),
                 page: int = Query(1, ge=1), sort: str = Query('latest', pattern='^(latest|official)$')):
        a, m, s, se = t['articles'], t['article_sources'], t['sources'], t['source_entries']
        membership = select(m.c.article_id).join(s, m.c.source_id == s.c.id).where(s.c.in_scope == 1)
        if category:
            membership = membership.where(s.c.category_id == category)
        where = [a.c.kind == 'article', a.c.id.in_(membership)]
        if q:
            where.append(or_(a.c.title.contains(q, autoescape=True), a.c.subtitle.contains(q, autoescape=True)))
        position = select(func.min(se.c.source_position)).join(s, se.c.source_id == s.c.id).where(
            se.c.article_id == a.c.id, s.c.in_scope == 1, s.c.category_id == category).scalar_subquery()
        order = [func.coalesce(a.c.published, '').desc(), a.c.discovered.desc(), a.c.id]
        if sort == 'official':
            if not category:
                raise HTTPException(422, '官网顺序需要指定栏目')
            order = [position.is_(None), position, a.c.id]
        with engine.connect() as conn:
            total = conn.scalar(select(func.count()).select_from(a).where(*where))
            rows = conn.execute(select(a).where(*where).order_by(*order).limit(20).offset((page - 1) * 20)).mappings()
            return {'items': [dict(r) for r in rows], 'total': total, 'page': page}

    @app.get('/api/v1/jobs', dependencies=[Depends(admin), Depends(ready)])
    def jobs():
        with engine.connect() as conn:
            rows = conn.execute(select(t['jobs'].c.id, t['jobs'].c.kind, t['jobs'].c.state,
                t['jobs'].c.attempts, t['jobs'].c.error, t['jobs'].c.due)
                .order_by(t['jobs'].c.created.desc()).limit(100)).mappings()
            return {'items': [dict(r) for r in rows]}

    return app
