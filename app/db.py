from __future__ import annotations
import contextlib
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import time

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('EXPORT_WATCH_DATA',ROOT/'data'))
DB=DATA/'observatory.sqlite3'


@contextlib.contextmanager
def connection():
    DATA.mkdir(parents=True,exist_ok=True)
    conn=sqlite3.connect(DB,timeout=30)
    conn.row_factory=sqlite3.Row
    conn.execute('PRAGMA foreign_keys=ON')
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def migrate_v2(conn):
    """Atomic v1 upgrade; preserve records, versions and provenance."""
    statements=[
      'CREATE TABLE countries(code TEXT PRIMARY KEY,name TEXT NOT NULL UNIQUE)',
      'CREATE TABLE publishers(id TEXT PRIMARY KEY,country_code TEXT NOT NULL REFERENCES countries(code),name TEXT NOT NULL,homepage TEXT NOT NULL)',
      'CREATE TABLE categories(id TEXT PRIMARY KEY,publisher_id TEXT NOT NULL REFERENCES publishers(id),parent_id TEXT REFERENCES categories(id),name TEXT NOT NULL,external_code TEXT,position INTEGER NOT NULL DEFAULT 0,UNIQUE(publisher_id,external_code))',
      'ALTER TABLE sources ADD COLUMN publisher_id TEXT REFERENCES publishers(id)',
      'ALTER TABLE sources ADD COLUMN category_id TEXT REFERENCES categories(id)',
      'ALTER TABLE sources ADD COLUMN in_scope INTEGER NOT NULL DEFAULT 0 CHECK(in_scope IN (0,1))',
      'ALTER TABLE sources ADD COLUMN name TEXT',
      'CREATE TABLE article_sources(article_id TEXT NOT NULL REFERENCES articles(id),source_id TEXT NOT NULL REFERENCES sources(id),first_seen REAL NOT NULL,last_seen REAL NOT NULL,external_key TEXT,source_page INTEGER,PRIMARY KEY(article_id,source_id))',
      'CREATE TABLE article_attachments(parent_id TEXT NOT NULL REFERENCES articles(id),attachment_id TEXT NOT NULL REFERENCES articles(id),first_seen REAL NOT NULL,PRIMARY KEY(parent_id,attachment_id),CHECK(parent_id!=attachment_id))',
      'CREATE TABLE file_versions(version_id INTEGER PRIMARY KEY REFERENCES versions(id),blob_digest TEXT NOT NULL REFERENCES file_blobs(digest))',
      'CREATE TABLE crawl_pages(id INTEGER PRIMARY KEY,run_id INTEGER NOT NULL REFERENCES runs(id),source_id TEXT NOT NULL REFERENCES sources(id),page_number INTEGER NOT NULL,item_count INTEGER NOT NULL,reported_total INTEGER,response_digest TEXT NOT NULL,checked REAL NOT NULL,UNIQUE(run_id,page_number))',
      'ALTER TABLE runs ADD COLUMN details TEXT',
    ]
    for sql in statements:conn.execute(sql)
    country_names={'CN':'中国','US':'美国','EU':'欧盟','DE':'德国'}
    conn.execute("INSERT INTO countries VALUES('CN','中国')")
    codes={'中国':'CN','美国':'US','欧盟':'EU','德国':'DE'}
    for source in conn.execute('SELECT * FROM sources').fetchall():
        cfg=json.loads(source['config']);code=codes.get(cfg.get('group'),'CN');pid='legacy-'+code;cid='legacy-'+source['id']
        conn.execute('INSERT OR IGNORE INTO countries VALUES(?,?)',(code,country_names.get(code,code)))
        conn.execute('INSERT OR IGNORE INTO publishers VALUES(?,?,?,?)',(pid,code,'历史来源（已归档）',cfg['url']))
        conn.execute('INSERT INTO categories(id,publisher_id,name) VALUES(?,?,?)',(cid,pid,'历史入口 · '+source['id']))
        conn.execute('UPDATE sources SET publisher_id=?,category_id=?,in_scope=0,paused=1,name=? WHERE id=?',(pid,cid,'历史入口 · '+source['id'],source['id']))
    original=[dict(x) for x in conn.execute('SELECT * FROM articles ORDER BY discovered,id')]
    keep_by_url={};mapping={}
    for article in original:
        keeper=keep_by_url.setdefault(article['url'],article['id']);mapping[article['id']]=keeper
        conn.execute('INSERT INTO article_sources(article_id,source_id,first_seen,last_seen) VALUES(?,?,?,?) ON CONFLICT(article_id,source_id) DO UPDATE SET first_seen=MIN(first_seen,excluded.first_seen),last_seen=MAX(last_seen,excluded.last_seen)',(keeper,article['source_id'],article['discovered'],article['discovered']))
        if keeper==article['id']:continue
        old_id=article['id']
        for v in conn.execute('SELECT * FROM versions WHERE article_id=?',(old_id,)).fetchall():
            same=conn.execute('SELECT * FROM versions WHERE article_id=? AND stamp=?',(keeper,v['stamp'])).fetchone()
            if same and same['digest']==v['digest']:
                conn.execute('UPDATE events SET version_id=? WHERE version_id=?',(same['id'],v['id']))
                conn.execute('DELETE FROM versions WHERE id=?',(v['id'],))
            else:
                stamp=v['stamp']+':legacy:'+str(v['id']) if same else v['stamp']
                conn.execute('UPDATE versions SET article_id=?,stamp=? WHERE id=?',(keeper,stamp,v['id']))
        conn.execute('UPDATE events SET article_id=? WHERE article_id=?',(keeper,old_id))
        conn.execute('UPDATE articles SET watch_id=COALESCE(watch_id,?) WHERE id=?',(article['watch_id'],keeper))
        conn.execute('UPDATE articles SET parent_id=? WHERE parent_id=?',(keeper,old_id))
        old_check=conn.execute('SELECT checked FROM file_checks WHERE article_id=?',(old_id,)).fetchone()
        if old_check:
            conn.execute('INSERT INTO file_checks VALUES(?,?) ON CONFLICT(article_id) DO UPDATE SET checked=MAX(checked,excluded.checked)',(keeper,old_check['checked']))
            conn.execute('DELETE FROM file_checks WHERE article_id=?',(old_id,))
        conn.execute('DELETE FROM articles WHERE id=?',(old_id,))
    for article in original:
        if article['parent_id']:
            parent=mapping.get(article['parent_id'],article['parent_id']);child=mapping[article['id']]
            if parent!=child:conn.execute('INSERT OR IGNORE INTO article_attachments VALUES(?,?,?)',(parent,child,article['discovered']))
    for v in conn.execute('SELECT id,content FROM versions').fetchall():
        match=re.search(r'SHA-256: ([0-9a-f]{64})',v['content'])
        if match and conn.execute('SELECT 1 FROM file_blobs WHERE digest=?',(match.group(1),)).fetchone():conn.execute('INSERT INTO file_versions VALUES(?,?)',(v['id'],match.group(1)))
    conn.execute('ALTER TABLE articles RENAME COLUMN source_id TO origin_source_id')
    conn.execute("DELETE FROM metadata WHERE key LIKE 'control:%'")
    for sql in [
      'CREATE UNIQUE INDEX articles_canonical_url ON articles(url)',
      'CREATE INDEX article_sources_source ON article_sources(source_id,article_id)',
      'CREATE INDEX versions_article ON versions(article_id,id)',
      'CREATE INDEX events_article_unread ON events(article_id,unread)',
      'CREATE INDEX sources_scope ON sources(in_scope,paused,next_check)',
      'CREATE INDEX attachment_children ON article_attachments(attachment_id,parent_id)',
    ]:conn.execute(sql)
    conn.execute('PRAGMA user_version=2')


def seed_sources(conn):
    conn.execute("INSERT OR IGNORE INTO countries VALUES('CN','中国')")
    conn.execute("INSERT OR IGNORE INTO publishers VALUES('cn-exportcontrol','CN','中国出口管制信息网','https://exportcontrol.mofcom.gov.cn/')")
    sources=json.loads((ROOT/'config/sources.json').read_text(encoding='utf-8'));configured={s['id'] for s in sources}
    for old in conn.execute('SELECT id FROM sources').fetchall():
        if old['id'] not in configured:conn.execute('UPDATE sources SET in_scope=0,paused=1 WHERE id=?',(old['id'],))
    for i,s in enumerate(sources):
        parent_position=0 if s['role']=='primary' else 100
        conn.execute('INSERT INTO categories(id,publisher_id,name,position) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,position=excluded.position',(s['parent_id'],s['publisher_id'],s['parent_name'],parent_position))
        conn.execute('INSERT INTO categories(id,publisher_id,parent_id,name,external_code,position) VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET parent_id=excluded.parent_id,name=excluded.name,external_code=excluded.external_code,position=excluded.position',(s['category_id'],s['publisher_id'],s['parent_id'],s['name'],str(s['column_id']),i))
        conn.execute('INSERT INTO sources(id,config,publisher_id,category_id,in_scope,name,scope_id) VALUES(?,?,?,?,1,?,?) ON CONFLICT(id) DO UPDATE SET config=excluded.config,publisher_id=excluded.publisher_id,category_id=excluded.category_id,in_scope=1,name=excluded.name,scope_id=excluded.scope_id',(s['id'],json.dumps(s,ensure_ascii=False),s['publisher_id'],s['category_id'],s['name'],'china-exportcontrol'))


def migrate_v3(conn):
    conn.execute('CREATE TABLE source_entries(source_id TEXT NOT NULL REFERENCES sources(id),external_key TEXT NOT NULL,article_id TEXT NOT NULL REFERENCES articles(id),source_page INTEGER,raw_title TEXT,first_seen REAL NOT NULL,last_seen REAL NOT NULL,PRIMARY KEY(source_id,external_key))')
    conn.execute('INSERT INTO source_entries(source_id,external_key,article_id,source_page,first_seen,last_seen) SELECT source_id,external_key,article_id,source_page,first_seen,last_seen FROM article_sources WHERE external_key IS NOT NULL')
    conn.execute('CREATE INDEX source_entries_article ON source_entries(article_id,source_id)')
    conn.execute('PRAGMA user_version=3')


def migrate_v4(conn):
    """Make the active China-only storage boundary explicit and enforceable."""
    conn.execute("INSERT OR IGNORE INTO countries VALUES('CN','中国')")
    conn.execute("INSERT OR IGNORE INTO publishers VALUES('cn-exportcontrol','CN','中国出口管制信息网','https://exportcontrol.mofcom.gov.cn/')")
    conn.execute('CREATE TABLE data_scopes(id TEXT PRIMARY KEY,country_code TEXT NOT NULL REFERENCES countries(code),publisher_id TEXT NOT NULL REFERENCES publishers(id),name TEXT NOT NULL,created REAL NOT NULL)')
    conn.execute('ALTER TABLE sources ADD COLUMN scope_id TEXT REFERENCES data_scopes(id)')
    conn.execute('INSERT INTO data_scopes VALUES(?,?,?,?,?)',('china-exportcontrol','CN','cn-exportcontrol','中国出口管制信息监测',time.time()))
    conn.execute("UPDATE sources SET scope_id='china-exportcontrol' WHERE in_scope=1 AND publisher_id='cn-exportcontrol'")
    conn.execute("CREATE TRIGGER sources_active_scope_insert BEFORE INSERT ON sources WHEN NEW.in_scope=1 AND NEW.scope_id IS NULL BEGIN SELECT RAISE(ABORT,'active source requires scope'); END")
    conn.execute("CREATE TRIGGER sources_active_scope_update BEFORE UPDATE OF in_scope,scope_id ON sources WHEN NEW.in_scope=1 AND NEW.scope_id IS NULL BEGIN SELECT RAISE(ABORT,'active source requires scope'); END")
    conn.execute('CREATE INDEX sources_scope_id ON sources(scope_id,in_scope,paused)')
    conn.execute('PRAGMA user_version=4')


def migrate_v5(conn):
    """Preserve each official column's displayed order for category views."""
    conn.execute('ALTER TABLE source_entries ADD COLUMN source_position INTEGER')
    conn.execute('''UPDATE source_entries SET source_position=(
      SELECT COUNT(*) FROM source_entries older
      WHERE older.source_id=source_entries.source_id AND older.rowid<=source_entries.rowid
    )''')
    conn.execute('CREATE INDEX source_entries_position ON source_entries(source_id,source_position)')
    conn.execute('PRAGMA user_version=5')


def init():
    with connection() as conn:
        conn.execute('PRAGMA journal_mode=WAL')
        conn.executescript('''
        CREATE TABLE IF NOT EXISTS sources(id TEXT PRIMARY KEY,config TEXT NOT NULL,paused INTEGER NOT NULL DEFAULT 0,hours INTEGER NOT NULL DEFAULT 6,state TEXT NOT NULL DEFAULT 'pending',error TEXT NOT NULL DEFAULT '',last_check REAL,last_success REAL,next_check REAL NOT NULL DEFAULT 0,initialized INTEGER NOT NULL DEFAULT 0,coverage TEXT NOT NULL DEFAULT '尚未建立基线');
        CREATE TABLE IF NOT EXISTS articles(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),url TEXT NOT NULL,title TEXT NOT NULL,published TEXT,description TEXT NOT NULL DEFAULT '',discovered REAL NOT NULL,watch_id TEXT,kind TEXT NOT NULL DEFAULT 'article',parent_id TEXT,error TEXT NOT NULL DEFAULT '',UNIQUE(source_id,url));
        CREATE TABLE IF NOT EXISTS versions(id INTEGER PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),stamp TEXT NOT NULL,content TEXT NOT NULL,digest TEXT NOT NULL,created REAL NOT NULL,UNIQUE(article_id,stamp));
        CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),kind TEXT NOT NULL,created REAL NOT NULL,unread INTEGER NOT NULL DEFAULT 1,version_id INTEGER REFERENCES versions(id));
        CREATE TABLE IF NOT EXISTS runs(id INTEGER PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),started REAL NOT NULL,finished REAL,state TEXT NOT NULL,count INTEGER NOT NULL DEFAULT 0,message TEXT NOT NULL DEFAULT '');
        CREATE TABLE IF NOT EXISTS metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS file_checks(article_id TEXT PRIMARY KEY REFERENCES articles(id),checked REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS file_blobs(digest TEXT PRIMARY KEY,path TEXT NOT NULL,bytes INTEGER NOT NULL);
        ''')
        conn.execute('BEGIN IMMEDIATE')
        if conn.execute('PRAGMA user_version').fetchone()[0]<2:migrate_v2(conn)
        if conn.execute('PRAGMA user_version').fetchone()[0]<3:migrate_v3(conn)
        if conn.execute('PRAGMA user_version').fetchone()[0]<4:migrate_v4(conn)
        if conn.execute('PRAGMA user_version').fetchone()[0]<5:migrate_v5(conn)
        seed_sources(conn)
        conn.execute("UPDATE runs SET state='interrupted',finished=?,message='上次运行中断，将在恢复后重新检查' WHERE state='running'",(time.time(),))
        if conn.execute('PRAGMA foreign_key_check').fetchall():raise RuntimeError('数据库关系校验失败，迁移已回滚')


def add_article(conn,source_id,item,baseline):
    now=time.time();existing=conn.execute('SELECT * FROM articles WHERE url=?',(item['url'],)).fetchone()
    aid=existing['id'] if existing else hashlib.sha256(item['url'].encode()).hexdigest()[:24];fresh=existing is None
    if fresh:
        conn.execute('INSERT INTO articles(id,origin_source_id,url,title,published,description,discovered,kind,parent_id) VALUES(?,?,?,?,?,?,?,?,?)',(aid,source_id,item['url'],item['title'],item.get('published'),item.get('description',''),now,item.get('kind','article'),item.get('parent_id')))
        if not baseline:conn.execute('INSERT OR IGNORE INTO events(id,article_id,kind,created) VALUES(?,?,?,?)',(aid+':new',aid,'attachment_added' if item.get('kind')=='attachment' else 'new',now))
    else:
        title=item['title']
        if title.startswith('官方文章 · ') and existing['title'].count('?')<4 and not existing['title'].startswith('官方文章 · '):title=existing['title']
        conn.execute("UPDATE articles SET title=?,published=COALESCE(?,published),description=CASE WHEN ?!='' THEN ? ELSE description END WHERE id=?",(title,item.get('published'),item.get('description',''),item.get('description',''),aid))
    conn.execute('INSERT INTO article_sources(article_id,source_id,first_seen,last_seen,external_key,source_page) VALUES(?,?,?,?,?,?) ON CONFLICT(article_id,source_id) DO UPDATE SET last_seen=excluded.last_seen,external_key=COALESCE(excluded.external_key,external_key),source_page=COALESCE(excluded.source_page,source_page)',(aid,source_id,now,now,item.get('external_id'),item.get('source_page')))
    if item.get('external_id'):
        conn.execute('INSERT INTO source_entries(source_id,external_key,article_id,source_page,source_position,raw_title,first_seen,last_seen) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(source_id,external_key) DO UPDATE SET article_id=excluded.article_id,source_page=excluded.source_page,source_position=COALESCE(excluded.source_position,source_entries.source_position),raw_title=excluded.raw_title,last_seen=excluded.last_seen',(source_id,item['external_id'],aid,item.get('source_page'),item.get('source_position'),item.get('raw_title',item['title']),now,now))
    parent=item.get('parent_id')
    if parent and parent!=aid:conn.execute('INSERT OR IGNORE INTO article_attachments VALUES(?,?,?)',(parent,aid,now))
    return aid,fresh


def add_version(conn,aid,stamp,content,baseline=False):
    digest=hashlib.sha256(content.encode()).hexdigest();previous=conn.execute('SELECT digest FROM versions WHERE article_id=? ORDER BY id DESC LIMIT 1',(aid,)).fetchone()
    if previous and previous['digest']==digest:return False
    cursor=conn.execute('INSERT OR IGNORE INTO versions(article_id,stamp,content,digest,created) VALUES(?,?,?,?,?)',(aid,str(stamp),content,digest,time.time()))
    if not cursor.rowcount:return False
    if previous and not baseline:conn.execute('INSERT OR IGNORE INTO events(id,article_id,kind,created,version_id) VALUES(?,?,?,?,?)',(f'{aid}:{stamp}',aid,'changed',time.time(),cursor.lastrowid))
    return True


def locations(conn,aid):
    return [dict(r) for r in conn.execute('''SELECT s.id AS source_id,s.name AS source_name,c.id AS category_id,c.name AS category_name,c.external_code,parent.name AS parent_category,json_extract(s.config,'$.role') AS role,p.name AS publisher,p.homepage,co.code AS country_code,co.name AS country,m.first_seen,m.last_seen,m.source_page,m.external_key
      FROM article_sources m JOIN sources s ON s.id=m.source_id JOIN categories c ON c.id=s.category_id LEFT JOIN categories parent ON parent.id=c.parent_id JOIN publishers p ON p.id=s.publisher_id JOIN countries co ON co.code=p.country_code
      WHERE m.article_id=? AND s.in_scope=1 ORDER BY c.position,s.id''',(aid,))]


SCOPED_ARTICLES="""SELECT a.*,COALESCE(MIN(CASE WHEN s.paused=0 THEN s.hours END),MIN(s.hours)) AS hours,MIN(s.paused) AS paused,
 (SELECT s2.id FROM article_sources m2 JOIN sources s2 ON s2.id=m2.source_id WHERE m2.article_id=a.id AND s2.in_scope=1 ORDER BY s2.id LIMIT 1) AS source_id
 FROM articles a JOIN article_sources m ON m.article_id=a.id JOIN sources s ON s.id=m.source_id WHERE s.in_scope=1 GROUP BY a.id"""
