"""Private server foundation. No anonymous data or legacy mutation endpoints."""
from contextlib import asynccontextmanager
import hmac
import difflib
import re
from fastapi import FastAPI, Depends, HTTPException, Query
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import FileResponse
from sqlalchemy import select, func, or_, literal, text
from backend.settings import Settings
from backend.storage import make_engine, tables as t, CURRENT_REVISION

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
                if version != CURRENT_REVISION:
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

    def scoped(conn, aid):
        a, m, s = t['articles'], t['article_sources'], t['sources']
        row = conn.execute(select(a).where(a.c.id == aid, a.c.id.in_(
            select(m.c.article_id).join(s, s.c.id == m.c.source_id).where(s.c.in_scope == 1)))).mappings().first()
        if not row:
            raise HTTPException(404, '信息不在当前监测范围内')
        return dict(row)

    @app.get('/api/v1/articles/{aid}', dependencies=[Depends(admin), Depends(ready)])
    def detail(aid: str):
        with engine.connect() as conn:
            article = scoped(conn, aid)
            versions = list(conn.execute(select(t['versions']).where(t['versions'].c.article_id == aid)
                .order_by(t['versions'].c.id.desc()).limit(30)).mappings())
            attachments = list(conn.execute(select(t['articles']).join(t['article_attachments'],
                t['article_attachments'].c.attachment_id == t['articles'].c.id)
                .where(t['article_attachments'].c.parent_id == aid)).mappings())
            state = conn.execute(select(t['monitor_states']).where(t['monitor_states'].c.article_id == aid)).mappings().first()
            locations = conn.execute(select(t['sources'].c.id, t['sources'].c.name, t['sources'].c.category_id)
                .join(t['article_sources'], t['article_sources'].c.source_id == t['sources'].c.id)
                .where(t['article_sources'].c.article_id == aid, t['sources'].c.in_scope == 1)).mappings().all()
        article.update(versions=[dict(r) for r in versions], attachments=[dict(r) for r in attachments],
                       monitoring=dict(state) if state else None, locations=[dict(r) for r in locations],
                       diff=list(difflib.unified_diff(versions[1]['content'].splitlines(), versions[0]['content'].splitlines(),
                           fromfile='上一个版本', tofile='当前版本', lineterm='')) if len(versions) > 1 else [])
        return article

    @app.get('/api/v1/attachments/{aid}/download', dependencies=[Depends(admin), Depends(ready)])
    def download(aid: str):
        with engine.connect() as conn:
            article = scoped(conn, aid)
            digest = conn.scalar(select(t['file_versions'].c.blob_digest).join(t['versions'],
                t['versions'].c.id == t['file_versions'].c.version_id)
                .where(t['versions'].c.article_id == aid).order_by(t['versions'].c.id.desc()).limit(1))
        if not digest or not re.fullmatch('[0-9a-f]{64}', digest):
            raise HTTPException(404, '附件尚未保存')
        folder = settings.files_root.resolve() / 'attachments'
        path = (folder / digest).resolve()
        if path.parent != folder or not path.is_file():
            raise HTTPException(404, '附件文件不可用')
        return FileResponse(path, media_type='application/octet-stream',
                            filename=re.sub(r'[<>:"/\\|?*]', '_', article['title'])[:180])

    return app
