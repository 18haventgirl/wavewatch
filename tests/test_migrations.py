import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from app import db


class MigrationTests(unittest.TestCase):
    def test_v1_upgrade_merges_duplicate_url_and_retains_history(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(db,'DATA',Path(folder)),patch.object(db,'DB',Path(folder)/'migration.sqlite3'):
            conn=sqlite3.connect(db.DB)
            conn.executescript('''
            CREATE TABLE sources(id TEXT PRIMARY KEY,config TEXT NOT NULL,paused INTEGER NOT NULL DEFAULT 0,hours INTEGER NOT NULL DEFAULT 6,state TEXT NOT NULL DEFAULT 'pending',error TEXT NOT NULL DEFAULT '',last_check REAL,last_success REAL,next_check REAL NOT NULL DEFAULT 0,initialized INTEGER NOT NULL DEFAULT 0,coverage TEXT NOT NULL DEFAULT 'old');
            CREATE TABLE articles(id TEXT PRIMARY KEY,source_id TEXT NOT NULL REFERENCES sources(id),url TEXT NOT NULL,title TEXT NOT NULL,published TEXT,description TEXT NOT NULL DEFAULT '',discovered REAL NOT NULL,watch_id TEXT,kind TEXT NOT NULL DEFAULT 'article',parent_id TEXT,error TEXT NOT NULL DEFAULT '',UNIQUE(source_id,url));
            CREATE TABLE versions(id INTEGER PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),stamp TEXT NOT NULL,content TEXT NOT NULL,digest TEXT NOT NULL,created REAL NOT NULL,UNIQUE(article_id,stamp));
            CREATE TABLE events(id TEXT PRIMARY KEY,article_id TEXT NOT NULL REFERENCES articles(id),kind TEXT NOT NULL,created REAL NOT NULL,unread INTEGER NOT NULL DEFAULT 1,version_id INTEGER REFERENCES versions(id));
            PRAGMA user_version=1;
            ''')
            for sid in ['old-a','old-b']:
                conn.execute('INSERT INTO sources(id,config) VALUES(?,?)',(sid,json.dumps({'group':'中国','url':'https://exportcontrol.mofcom.gov.cn/'})))
            url='https://exportcontrol.mofcom.gov.cn/article/example.html'
            conn.execute("INSERT INTO articles(id,source_id,url,title,discovered) VALUES('a','old-a',?,'old title',1)",(url,))
            conn.execute("INSERT INTO articles(id,source_id,url,title,discovered,watch_id) VALUES('b','old-b',?,'old title',2,'watch-b')",(url,))
            conn.execute("INSERT INTO versions VALUES(1,'a','10','body','hash',1)")
            conn.execute("INSERT INTO versions VALUES(2,'b','10','body','hash',1)")
            conn.execute("INSERT INTO events VALUES('event-b','b','changed',2,1,2)")
            conn.commit();conn.close()
            db.init();db.init()
            with db.connection() as c:
                self.assertEqual(c.execute('PRAGMA user_version').fetchone()[0],5)
                self.assertEqual(c.execute('SELECT count(*) FROM articles').fetchone()[0],1)
                self.assertEqual(c.execute('SELECT count(*) FROM versions').fetchone()[0],1)
                event=c.execute('SELECT article_id,version_id FROM events').fetchone()
                self.assertEqual(tuple(event),('a',1))
                self.assertEqual(c.execute('SELECT watch_id FROM articles').fetchone()[0],'watch-b')
                self.assertEqual(c.execute('SELECT count(*) FROM article_sources').fetchone()[0],2)
                self.assertEqual(c.execute("SELECT SUM(paused) FROM sources WHERE id LIKE 'old-%'").fetchone()[0],2)
                reused,fresh=db.add_article(c,'cn-policy-laws',{'url':url,'title':'核实的标题'},True)
                self.assertEqual(reused,'a');self.assertFalse(fresh)
                self.assertEqual(db.locations(c,'a')[0]['category_name'],'法律')
                self.assertEqual(c.execute('PRAGMA foreign_key_check').fetchall(),[])


if __name__=='__main__':unittest.main()
