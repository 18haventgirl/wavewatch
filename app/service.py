from __future__ import annotations
import concurrent.futures
import json
import threading
import time
import hashlib
import subprocess
import sys
from . import db, engine, collectors

NAMES={'cn-domestic':'国内动态','cn-international':'国际动态','cn-laws':'政策法规','cn-faq':'常见问题',
       'us-guide':'出口管制介绍','us-bis-news':'BIS 新闻公告','us-bis-rules':'BIS 法规公告',
       'us-fr-bis':'Federal Register · BIS','eu-map':'EU Sanctions Map','de-bafa-home':'BAFA 外贸栏目','de-bafa-rss':'BAFA 外贸 RSS'}
NAMES.update({'cn-policy-laws':'法律','cn-policy-regulations':'法规','cn-policy-rules':'规章及规范性文件',
              'cn-news-domestic':'国内动态','cn-news-international':'国际动态'})
locks={}
active=set()
attachment_jobs=set()
title_jobs=set()
guard=threading.Lock()
stop=threading.Event()
pool=concurrent.futures.ThreadPoolExecutor(max_workers=3,thread_name_prefix='discovery')
title_pool=concurrent.futures.ThreadPoolExecutor(max_workers=4,thread_name_prefix='titles')


def safe_error(exc):
    if isinstance(exc, collectors.httpx.HTTPStatusError):
        return f'原站返回 HTTP {exc.response.status_code}，本次未通过采集验证'
    message=str(exc)
    if 'CERTIFICATE' in message or 'certificate' in message:
        return '证书信任链验证失败；已保留安全校验，待核对本机网络环境'
    if 'timed out' in message.lower():
        return '原站请求超时，将在后续检查中重试'
    return message[:400]


def check_source(sid):
    with guard:
        if sid in active:
            return False
        active.add(sid)
    pool.submit(run_source,sid)
    return True


def run_source(sid):
    started=time.time()
    run_id=None
    try:
        with db.connection() as conn:
            row=conn.execute('SELECT * FROM sources WHERE id=?',(sid,)).fetchone()
            if not row or row['paused'] or not row['in_scope']:
                return
            source=json.loads(row['config'])
            conn.execute("UPDATE sources SET state='checking',last_check=? WHERE id=?",(started,sid))
            run_id=conn.execute("INSERT INTO runs(source_id,started,state) VALUES(?,?,'running')",(sid,started)).lastrowid
        lock=locks.setdefault(collectors.urlsplit(source['url']).hostname,threading.Lock())
        with lock:
            records,coverage,pages=collectors.discover(source)
        with db.connection() as conn:
            total_new=0
            for item in records:
                _,fresh=db.add_article(conn,sid,item,baseline=not row['initialized'])
                total_new+=int(fresh)
            conn.execute("UPDATE sources SET state='discovered', error='',initialized=1,last_success=?,next_check=?,coverage=? WHERE id=?",
                         (time.time(),started+row['hours']*3600,coverage,sid))
            for page in pages:
                conn.execute('INSERT INTO crawl_pages(run_id,source_id,page_number,item_count,reported_total,response_digest,checked) VALUES(?,?,?,?,?,?,?)',(run_id,sid,page['page_number'],page['item_count'],page['reported_total'],page['response_digest'],page['checked']))
            conn.execute("UPDATE runs SET finished=?,state='success',count=?,message=?,details=? WHERE id=?",
                         (time.time(),len(records),f'解析 {len(records)} 条，新增 {total_new} 条；'+coverage,json.dumps({'pages':len(pages),'reported_total':pages[0]['reported_total'] if pages else None,'valid_items':len(records),'unique_articles':len({r['url'] for r in records}),'duplicate_links':len(records)-len({r['url'] for r in records})}),run_id))
    except Exception as exc:
        reason=safe_error(exc)
        with db.connection() as conn:
            # Failed checks retry in one hour; no tight request loop.
            conn.execute("UPDATE sources SET state='error',error=?,next_check=? WHERE id=?",(reason,time.time()+3600,sid))
            if run_id:
                conn.execute("UPDATE runs SET finished=?,state='error',message=? WHERE id=?",(time.time(),reason,run_id))
    finally:
        with guard:
            active.discard(sid)


def hydrate_title(article):
    """Resolve a damaged list title from its official article page."""
    try:
        body,_=collectors.fetch(article['url'])
        title=collectors.article_title(body)
        if not title or collectors.bad_title(title):
            raise ValueError('官方文章页未提供可用标题')
        with db.connection() as conn:
            conn.execute("UPDATE articles SET title=?,description='',error=CASE WHEN error LIKE '标题核实未完成：%' THEN '' ELSE error END WHERE id=?",(title,article['id']))
            conn.execute('DELETE FROM metadata WHERE key=?',('title-retry:'+article['id'],))
    except Exception as exc:
        with db.connection() as conn:
            conn.execute('INSERT INTO metadata(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value',('title-retry:'+article['id'],str(time.time()+3600)))
            conn.execute('UPDATE articles SET error=? WHERE id=?',('标题核实未完成：'+safe_error(exc),article['id']))
    finally:
        with guard:
            title_jobs.discard(article['id'])


def queue_title_hydration():
    """Keep title repair independent from the slower snapshot/watch queue."""
    now=time.time()
    with db.connection() as conn:
        rows=conn.execute("""SELECT q.* FROM ("""+db.SCOPED_ARTICLES+""") q
          WHERE q.kind!='attachment' AND q.paused=0
            AND (q.title LIKE '官方文章 · %' OR q.title LIKE '%�%')
            AND NOT EXISTS(SELECT 1 FROM metadata m WHERE m.key='title-retry:'||q.id AND CAST(m.value AS REAL)>?)
          ORDER BY q.discovered DESC LIMIT 80""",(now,)).fetchall()
    with guard:
        available=max(0,24-len(title_jobs))
        selected=[]
        for row in rows:
            if available<=0:break
            if row['id'] in title_jobs:continue
            title_jobs.add(row['id']);selected.append(dict(row));available-=1
    for article in selected:
        future=title_pool.submit(hydrate_title,article)
        future.add_done_callback(refill_title_queue)


def refill_title_queue(_future):
    """Keep all bounded title workers busy without waiting for the next sync tick."""
    if stop.is_set():
        return
    try:
        queue_title_hydration()
    except Exception:
        # The periodic synchronizer remains the recovery path.
        pass


def discover_attachments(article, baseline):
    try:
        body,_=collectors.fetch(article['url'])
        if collectors.bad_title(article['title']):
            title=collectors.article_title(body)
            if title and not collectors.bad_title(title):
                with db.connection() as conn:
                    conn.execute("UPDATE articles SET title=?,description='' WHERE id=?",(title,article['id']))
        items=collectors.attachments(article['url'],body)
        with db.connection() as conn:
            memberships=[x['source_id'] for x in conn.execute('SELECT m.source_id FROM article_sources m JOIN sources s ON s.id=m.source_id WHERE m.article_id=? AND s.in_scope=1',(article['id'],))]
            for item in items:
                item['parent_id']=article['id']
                for sid in memberships:db.add_article(conn,sid,item,baseline)
    except Exception as exc:
        with db.connection() as conn:
            conn.execute('UPDATE articles SET error=? WHERE id=?',('附件发现未完成：'+safe_error(exc),article['id']))
    finally:
        with guard:
            attachment_jobs.discard(article['id'])


def sync_file(article):
    with db.connection() as conn:
        last=conn.execute('SELECT checked FROM file_checks WHERE article_id=?',(article['id'],)).fetchone()
    if last and last['checked']+article['hours']*3600>time.time():
        return
    body,ctype=collectors.fetch(article['url'])
    if 'html' in ctype:
        collectors.soup_of(body)
        raise ValueError('附件地址返回网页，未保存为文件')
    digest=hashlib.sha256(body).hexdigest()
    folder=db.DATA/'attachments';folder.mkdir(exist_ok=True)
    file=folder/digest
    if not file.exists():
        file.write_bytes(body)
    text='此附件记录的是文件字节变化，不自动等于政策内容变化。\nSHA-256: '+digest+'\n文件大小: '+str(len(body))+' 字节\n'
    if body.startswith(b'%PDF'):
        try:
            result=subprocess.run([sys.executable,'-X','utf8',str(db.ROOT/'scripts'/'extract_pdf.py'),str(file)],capture_output=True,text=True,encoding='utf-8',errors='replace',timeout=20)
            text+='\n'+(result.stdout if result.returncode==0 else 'PDF 文本提取未完成，请查看原文件。')
        except subprocess.TimeoutExpired:
            text+='\nPDF 文本提取超时；文件版本已保存。'
    else:
        text+='\n此格式暂提供文件指纹和版本保存。'
    with db.connection() as conn:
        # The digest is part of the version, so binary-only revisions are retained.
        db.add_version(conn,article['id'],'file:'+str(time.time_ns()),text)
        conn.execute('INSERT OR IGNORE INTO file_blobs(digest,path,bytes) VALUES(?,?,?)',(digest,str(file),len(body)))
        vid=conn.execute('SELECT id FROM versions WHERE article_id=? ORDER BY id DESC LIMIT 1',(article['id'],)).fetchone()['id']
        conn.execute('INSERT OR IGNORE INTO file_versions(version_id,blob_digest) VALUES(?,?)',(vid,digest))
        conn.execute('INSERT INTO file_checks(article_id,checked) VALUES(?,?) ON CONFLICT(article_id) DO UPDATE SET checked=excluded.checked',(article['id'],time.time()))
        conn.execute("UPDATE articles SET error='' WHERE id=?",(article['id'],))


def sync_engine():
    if not engine.health()['online']:
        return
    with db.connection() as conn:
        pending=conn.execute("SELECT key,value FROM metadata WHERE key LIKE 'control:%' LIMIT 20").fetchall()
    for entry in pending:
        try:
            engine.api('watch/'+entry['key'].split(':',1)[1],'PUT',json.loads(entry['value']))
            with db.connection() as conn:
                conn.execute('DELETE FROM metadata WHERE key=?',(entry['key'],))
        except Exception:
            pass
    with db.connection() as conn:
        missing=conn.execute("SELECT * FROM ("+db.SCOPED_ARTICLES+") WHERE watch_id IS NULL AND kind!='attachment' AND paused=0 ORDER BY discovered DESC LIMIT 12").fetchall()
    for row in missing:
        try:
            if collectors.bad_title(row['title']):
                body,_=collectors.fetch(row['url'])
                title=collectors.article_title(body)
                if title and not collectors.bad_title(title):
                    row=dict(row)|{'title':title}
                    with db.connection() as conn:
                        conn.execute("UPDATE articles SET title=?,description='' WHERE id=?",(title,row['id']))
            wid=engine.register(row,row['hours'])
            with db.connection() as conn:
                conn.execute("UPDATE articles SET watch_id=?,error='' WHERE id=?",(wid,row['id']))
        except Exception as exc:
            with db.connection() as conn:
                conn.execute('UPDATE articles SET error=? WHERE id=?',(safe_error(exc),row['id']))
    with db.connection() as conn:
        # Rotate through tasks so newer tasks cannot starve older ones.
        cursor=int((conn.execute("SELECT value FROM metadata WHERE key='sync_cursor'").fetchone() or {'value':'0'})['value'])
        rows=conn.execute("SELECT * FROM ("+db.SCOPED_ARTICLES+") WHERE (watch_id IS NOT NULL OR kind='attachment') AND paused=0 ORDER BY id LIMIT 24 OFFSET ?",(cursor,)).fetchall()
        next_cursor=cursor+len(rows) if len(rows)==24 else 0
        conn.execute("INSERT INTO metadata(key,value) VALUES('sync_cursor',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(str(next_cursor),))
    for row in rows:
        if stop.is_set():
            break
        try:
            if row['kind']=='attachment' or any(collectors.urlsplit(row['url']).path.lower().endswith(ext) for ext in ('.pdf','.doc','.docx','.xls','.xlsx','.zip')):
                sync_file(row)
                continue
            watch=engine.api('watch/'+row['watch_id'])
            expected_filters=engine.filters_for(row)
            if watch.get('include_filters',[])!=expected_filters:
                engine.api('watch/'+row['watch_id'],'PUT',{'include_filters':expected_filters})
                with db.connection() as conn:
                    conn.execute('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)',('rebase:'+row['id'],'1'))
                engine.api('watch/'+row['watch_id']+'?recheck=1')
                continue
            with db.connection() as conn:
                desired=conn.execute('SELECT MIN(s.paused) AS paused,MIN(CASE WHEN s.paused=0 THEN s.hours END) AS hours FROM articles a JOIN article_sources m ON m.article_id=a.id JOIN sources s ON s.id=m.source_id WHERE a.watch_id=? AND s.in_scope=1',(row['watch_id'],)).fetchone()
            desired_hours=desired['hours'] or row['hours']
            if bool(watch.get('paused'))!=bool(desired['paused']) or watch.get('time_between_check',{}).get('hours')!=desired_hours:
                engine.api('watch/'+row['watch_id'],'PUT',{'paused':bool(desired['paused']),'time_between_check':{'hours':desired_hours},'time_between_check_use_default':False})
            if watch.get('last_error'):
                raise RuntimeError('正文/附件监测：'+str(watch['last_error'])[:250])
            history=engine.api('watch/'+row['watch_id']+'/history')
            stamps=sorted(history, key=lambda x:float(x)) if isinstance(history,dict) else []
            updated=False
            baseline=False
            for stamp in stamps[-3:]:
                with db.connection() as conn:
                    exists=conn.execute('SELECT id FROM versions WHERE article_id=? AND stamp=?',(row['id'],str(stamp))).fetchone()
                    baseline=not conn.execute('SELECT id FROM versions WHERE article_id=?',(row['id'],)).fetchone()
                if exists:
                    continue
                content=engine.api('watch/'+row['watch_id']+'/history/'+str(stamp))
                if not isinstance(content,str) or len(content.strip())<10:
                    raise RuntimeError('引擎快照内容不足，尚未通过正文验证')
                if len(content)>4*1024*1024:
                    raise RuntimeError('正文快照超过业务同步上限，尚未导入')
                if row['kind']!='attachment':
                    collectors.soup_of(content.encode())
                with db.connection() as conn:
                    rebase=conn.execute('SELECT value FROM metadata WHERE key=?',('rebase:'+row['id'],)).fetchone()
                    updated=db.add_version(conn,row['id'],stamp,content,baseline=bool(rebase)) or updated
                    if rebase:conn.execute('DELETE FROM metadata WHERE key=?',('rebase:'+row['id'],))
            with db.connection() as conn:
                conn.execute("UPDATE articles SET error='' WHERE id=?",(row['id'],))
            if updated and row['kind']!='attachment':
                with guard:
                    if row['id'] not in attachment_jobs:
                        attachment_jobs.add(row['id'])
                        pool.submit(discover_attachments,dict(row),baseline)
        except Exception as exc:
            with db.connection() as conn:
                conn.execute('UPDATE articles SET error=? WHERE id=?',(safe_error(exc),row['id']))


def scheduler():
    while not stop.is_set():
        with db.connection() as conn:
            due=conn.execute('SELECT id FROM sources WHERE in_scope=1 AND paused=0 AND next_check<=?',(time.time(),)).fetchall()
        for row in due:
            check_source(row['id'])
        stop.wait(10)


def synchronizer():
    while not stop.is_set():
        try:
            queue_title_hydration()
            sync_engine()
        except Exception:
            # Next cycle retries; the engine health is independently visible in UI.
            pass
        stop.wait(15)


def start():
    stop.clear()
    threads=[threading.Thread(target=scheduler,daemon=True),threading.Thread(target=synchronizer,daemon=True)]
    for thread in threads:
        thread.start()
    return threads
