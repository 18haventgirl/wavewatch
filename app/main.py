from __future__ import annotations
from contextlib import asynccontextmanager
import difflib
import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import FastAPI,HTTPException,Request
from fastapi.responses import FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from . import db,engine,service

SCOPE="EXISTS(SELECT 1 FROM article_sources sm JOIN sources ss ON ss.id=sm.source_id WHERE sm.article_id=a.id AND ss.in_scope=1)"
UNREAD="EXISTS(SELECT 1 FROM events e WHERE e.unread=1 AND (e.article_id=a.id OR EXISTS(SELECT 1 FROM article_attachments aa WHERE aa.parent_id=a.id AND aa.attachment_id=e.article_id)))"
CHANGED="EXISTS(SELECT 1 FROM events e WHERE e.kind='changed' AND (e.article_id=a.id OR EXISTS(SELECT 1 FROM article_attachments aa WHERE aa.parent_id=a.id AND aa.attachment_id=e.article_id)))"


@asynccontextmanager
async def lifespan(app):
    db.init();threads=service.start()
    yield
    service.stop.set()
    for thread in threads:thread.join(timeout=2)


app=FastAPI(title='观澜 · 中国出口管制政策监测',lifespan=lifespan,docs_url=None,redoc_url=None)


@app.middleware('http')
async def local_only(request:Request,call_next):
    if request.url.hostname not in ('127.0.0.1','localhost','testserver'):return JSONResponse({'detail':'仅允许本机访问'},status_code=403)
    origin=request.headers.get('origin')
    if request.method not in ('GET','HEAD','OPTIONS') and origin and urlsplit(origin).netloc!=request.url.netloc:return JSONResponse({'detail':'请求来源不符'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='no-referrer'
    return response


def scope_info(conn):
    categories=[dict(r) for r in conn.execute('SELECT c.id,c.name,c.external_code,parent.id AS parent_id,parent.name AS parent_name,json_extract(s.config,\'$.role\') AS role,s.id AS source_id,(SELECT count(*) FROM article_sources m JOIN articles a ON a.id=m.article_id WHERE m.source_id=s.id AND a.kind=\'article\') AS articles FROM categories c JOIN sources s ON s.category_id=c.id LEFT JOIN categories parent ON parent.id=c.parent_id WHERE s.in_scope=1 ORDER BY parent.position,c.position')]
    return {'country':'中国','country_code':'CN','publisher':'中国出口管制信息网','categories':categories,'archived_sources':conn.execute('SELECT count(*) FROM sources WHERE in_scope=0').fetchone()[0]}


@app.get('/api/taxonomy')
def taxonomy():
    with db.connection() as conn:return scope_info(conn)


@app.get('/api/dashboard')
def dashboard():
    with db.connection() as conn:
        sources=[]
        for row in conn.execute('SELECT s.*,c.name AS category_name,c.external_code,parent.name AS parent_category,p.name AS publisher,co.name AS country,co.code AS country_code FROM sources s JOIN categories c ON c.id=s.category_id LEFT JOIN categories parent ON parent.id=c.parent_id JOIN publishers p ON p.id=s.publisher_id JOIN countries co ON co.code=p.country_code WHERE s.in_scope=1 ORDER BY parent.position,c.position'):
            s=dict(row);config=json.loads(s.pop('config'));s.update(group=s['country'],url=config['url'],role=config['role'])
            s['articles']=conn.execute("SELECT count(*) FROM article_sources m JOIN articles a ON a.id=m.article_id WHERE m.source_id=? AND a.kind='article'",(s['id'],)).fetchone()[0]
            s['verified']=conn.execute("SELECT count(*) FROM article_sources m JOIN articles a ON a.id=m.article_id WHERE m.source_id=? AND a.kind='article' AND EXISTS(SELECT 1 FROM versions v WHERE v.article_id=a.id)",(s['id'],)).fetchone()[0]
            latest=conn.execute('SELECT details FROM runs WHERE source_id=? AND state=\'success\' ORDER BY id DESC LIMIT 1',(s['id'],)).fetchone()
            s['crawl']=json.loads(latest['details']) if latest and latest['details'] else None
            sources.append(s)
        base=" FROM articles a WHERE a.kind='article' AND "+SCOPE
        stats={'articles':conn.execute('SELECT count(*)'+base).fetchone()[0],
               'unread':conn.execute('SELECT count(*)'+base+' AND '+UNREAD).fetchone()[0],
               'revisions':conn.execute('SELECT count(*) FROM events e WHERE kind=\'changed\' AND EXISTS(SELECT 1 FROM articles a WHERE a.id=e.article_id AND '+SCOPE+')').fetchone()[0]}
        runs=[dict(x) for x in conn.execute('SELECT r.*,s.name,co.name AS "group" FROM runs r JOIN sources s ON s.id=r.source_id JOIN publishers p ON p.id=s.publisher_id JOIN countries co ON co.code=p.country_code WHERE s.in_scope=1 ORDER BY r.id DESC LIMIT 100')]
        scope=scope_info(conn)
    return {'sources':sources,'scope':scope,'stats':stats,'runs':runs,'engine':engine.health(),'now':time.time()}


def decorate(conn,row):
    item=dict(row);locations=db.locations(conn,item['id'])
    item.update(locations=locations,categories=[{'id':x['category_id'],'name':x['category_name'],'parent_name':x['parent_category'],'role':x['role'],'source_id':x['source_id']} for x in locations],source_id=locations[0]['source_id'] if locations else item.get('origin_source_id'),source_name=locations[0]['source_name'] if locations else '来源待核实',region=locations[0]['country'] if locations else '中国')
    return item


@app.get('/api/articles')
def articles(q:str='',group:str='',category:str='',unread:bool=False,kind:str='',page:int=1):
    where=["a.kind='article'",SCOPE];args=[]
    if q:where.append('(a.title LIKE ? OR a.description LIKE ?)');args.extend(['%'+q[:200]+'%']*2)
    if group and group!='中国':where.append('0')
    if category:
        where.append('EXISTS(SELECT 1 FROM article_sources cm JOIN sources cs ON cs.id=cm.source_id WHERE cm.article_id=a.id AND cs.in_scope=1 AND cs.category_id=?)');args.append(category)
    if unread:where.append(UNREAD)
    if kind=='changed':where.append(CHANGED)
    base=' FROM articles a WHERE '+' AND '.join(where)
    position_select='';select_args=[];order="COALESCE(a.published,'') DESC,a.discovered DESC,a.id"
    if category:
        position_select=",(SELECT MIN(se.source_position) FROM source_entries se JOIN sources os ON os.id=se.source_id WHERE se.article_id=a.id AND os.in_scope=1 AND os.category_id=?) AS source_position"
        select_args=[category]
        order="source_position IS NULL,source_position,a.id"
    with db.connection() as conn:
        total=conn.execute('SELECT count(*)'+base,args).fetchone()[0]
        rows=conn.execute('SELECT a.*'+position_select+',(SELECT count(*) FROM versions v WHERE v.article_id=a.id) AS version_count,('+UNREAD+') AS unread,('+CHANGED+') AS changes'+base+' ORDER BY '+order+' LIMIT 20 OFFSET ?',select_args+args+[max(0,page-1)*20]).fetchall()
        items=[decorate(conn,r) for r in rows]
    return {'items':items,'total':total,'page':page}


@app.get('/api/articles/{aid}')
def article(aid:str):
    with db.connection() as conn:
        row=conn.execute('SELECT a.* FROM articles a WHERE a.id=? AND '+SCOPE,(aid,)).fetchone()
        if not row:raise HTTPException(404,'信息不在当前监测范围内')
        result=decorate(conn,row)
        versions=[dict(x) for x in conn.execute('SELECT v.*,fv.blob_digest,b.bytes FROM versions v LEFT JOIN file_versions fv ON fv.version_id=v.id LEFT JOIN file_blobs b ON b.digest=fv.blob_digest WHERE article_id=? ORDER BY v.id DESC LIMIT 30',(aid,))]
        children=[decorate(conn,x) for x in conn.execute('SELECT a.*,(SELECT count(*) FROM versions v WHERE v.article_id=a.id) AS version_count FROM articles a JOIN article_attachments aa ON aa.attachment_id=a.id WHERE aa.parent_id=?',(aid,))]
        result.update(versions=versions,attachments=children,has_saved_file=any(x['blob_digest'] for x in versions))
        result['diff']=list(difflib.unified_diff(versions[1]['content'].splitlines(),versions[0]['content'].splitlines(),fromfile='上一个版本',tofile='当前版本',lineterm='')) if len(versions)>1 else []
    return result


@app.post('/api/articles/{aid}/read')
def mark_read(aid:str):
    with db.connection() as conn:
        if not conn.execute('SELECT a.id FROM articles a WHERE a.id=? AND '+SCOPE,(aid,)).fetchone():raise HTTPException(404,'信息不在当前监测范围内')
        conn.execute('UPDATE events SET unread=0 WHERE article_id=? OR article_id IN (SELECT attachment_id FROM article_attachments WHERE parent_id=?)',(aid,aid))
    return {'ok':True}


@app.post('/api/read-all')
def read_all():
    with db.connection() as conn:conn.execute('UPDATE events SET unread=0 WHERE article_id IN (SELECT a.id FROM articles a WHERE '+SCOPE+')')
    return {'ok':True}


@app.get('/api/attachments/{aid}/download')
def download_attachment(aid:str):
    with db.connection() as conn:
        article=conn.execute('SELECT a.* FROM articles a WHERE a.id=? AND '+SCOPE,(aid,)).fetchone()
        blob=conn.execute('SELECT b.path FROM file_versions f JOIN versions v ON v.id=f.version_id JOIN file_blobs b ON b.digest=f.blob_digest WHERE v.article_id=? ORDER BY v.id DESC LIMIT 1',(aid,)).fetchone()
    if not article or not blob:raise HTTPException(404,'附件尚未完成本机保存')
    file=Path(blob['path']).resolve()
    if file.parent!=(db.DATA/'attachments').resolve() or not file.is_file():raise HTTPException(404,'保存文件不可用')
    return FileResponse(file,filename=re.sub(r'[<>:"/\\|?*]','_',article['title'])[:180],media_type='application/octet-stream')


@app.post('/api/check')
def check_all():
    with db.connection() as conn:ids=[x['id'] for x in conn.execute('SELECT id FROM sources WHERE in_scope=1 AND paused=0')]
    return {'queued':sum(int(service.check_source(sid)) for sid in ids)}


class SourceSettings(BaseModel):
    paused:bool
    hours:int=Field(ge=1,le=168)


@app.put('/api/sources/{sid}')
def update_source(sid:str,settings:SourceSettings):
    with db.connection() as conn:
        row=conn.execute('SELECT * FROM sources WHERE id=? AND in_scope=1',(sid,)).fetchone()
        if not row:raise HTTPException(404,'来源不在当前监测范围内')
        conn.execute('UPDATE sources SET paused=?,hours=?,next_check=? WHERE id=?',(int(settings.paused),settings.hours,time.time() if not settings.paused and row['paused'] else time.time()+settings.hours*3600,sid))
        watches=conn.execute('''SELECT a.watch_id,MIN(s.paused) AS paused,MIN(CASE WHEN s.paused=0 THEN s.hours END) AS hours FROM articles a JOIN article_sources m ON m.article_id=a.id JOIN sources s ON s.id=m.source_id WHERE s.in_scope=1 AND a.watch_id IS NOT NULL AND EXISTS(SELECT 1 FROM article_sources x WHERE x.article_id=a.id AND x.source_id=?) GROUP BY a.watch_id''',(sid,)).fetchall()
        for watch in watches:
            payload={'paused':bool(watch['paused']),'time_between_check':{'hours':watch['hours'] or settings.hours},'time_between_check_use_default':False}
            conn.execute('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('control:'+watch['watch_id'],json.dumps(payload)))
    return {'ok':True,'pending_watches':len(watches)}


@app.post('/api/sources/{sid}/check')
def check_one(sid:str):
    with db.connection() as conn:row=conn.execute('SELECT paused FROM sources WHERE id=? AND in_scope=1',(sid,)).fetchone()
    if not row:raise HTTPException(404,'来源不在当前监测范围内')
    if row['paused']:raise HTTPException(409,'请先恢复该来源')
    return {'queued':service.check_source(sid)}


assets=db.ROOT/'frontend'/'dist'/'assets'
if assets.exists():app.mount('/assets',StaticFiles(directory=assets),name='assets')


@app.get('/')
def home():
    path=db.ROOT/'frontend'/'dist'/'index.html'
    if not path.exists():raise HTTPException(503,'前端尚未构建，请运行启动脚本')
    return FileResponse(path)
