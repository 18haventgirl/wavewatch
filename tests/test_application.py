import json
import io
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app import db,collectors,service
from app.main import app


class ApplicationTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.patches=[patch.object(db,'DATA',Path(self.temp.name)),patch.object(db,'DB',Path(self.temp.name)/'test.sqlite3'),patch.object(service,'start',return_value=[]),patch('app.engine.health',return_value={'online':False,'name':'test'})]
        for p in self.patches:p.start()
        self.client=TestClient(app)
        self.client.__enter__()

    def tearDown(self):
        self.client.__exit__(None,None,None)
        for p in reversed(self.patches):p.stop()
        self.temp.cleanup()

    def seed(self,baseline=True):
        with db.connection() as c:
            return db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/article/test.html','title':'受控测试公告','published':'2026-11-20'},baseline)[0]

    def test_baseline_dedup_no_unread(self):
        aid=self.seed()
        self.seed()
        with db.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM articles').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],0)
            db.add_version(c,aid,'1','first official content')
            db.add_version(c,aid,'1','first official content')
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['unread'],0)

    def test_revision_read_persistence(self):
        aid=self.seed()
        with db.connection() as c:
            db.add_version(c,aid,'1','original text')
            db.add_version(c,aid,'2','revised text')
            db.add_version(c,aid,'3','revised text')
        data=self.client.get('/api/articles?unread=true').json()
        self.assertEqual(data['total'],1)
        detail=self.client.get('/api/articles/'+aid).json()
        self.assertEqual(len(detail['versions']),2)
        self.assertTrue(detail['diff'])
        self.assertEqual(self.client.post('/api/articles/'+aid+'/read').status_code,200)
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['unread'],0)
        db.init()
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['unread'],0)

    def test_attachment_change_bubbles_to_parent(self):
        aid=self.seed()
        with db.connection() as c:
            fid,_=db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/test.pdf','title':'附件','kind':'attachment','parent_id':aid},True)
            db.add_version(c,fid,'file1','SHA-256: abc')
            db.add_version(c,fid,'file2','SHA-256: def')
        data=self.client.get('/api/articles?unread=true').json()
        self.assertEqual(data['items'][0]['id'],aid)
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['unread'],1)
        self.client.post('/api/articles/'+aid+'/read')
        self.assertEqual(self.client.get('/api/articles?unread=true').json()['total'],0)

    def test_source_failure_preserves_history(self):
        self.seed()
        with patch.object(collectors,'discover',side_effect=ValueError('empty challenge page')):
            service.run_source('cn-policy-laws')
        self.assertEqual(self.client.get('/api/articles').json()['total'],1)
        source=next(x for x in self.client.get('/api/dashboard').json()['sources'] if x['id']=='cn-policy-laws')
        self.assertEqual(source['state'],'error')
        self.assertIsNone(source['last_success'])

    def test_repeated_source_initialization_not_reset_settings(self):
        response=self.client.put('/api/sources/cn-policy-laws',json={'paused':True,'hours':12})
        self.assertEqual(response.status_code,200)
        db.init()
        source=next(x for x in self.client.get('/api/dashboard').json()['sources'] if x['id']=='cn-policy-laws')
        self.assertEqual(source['paused'],1)
        self.assertEqual(source['hours'],12)

    def test_cross_origin_mutation_rejected(self):
        self.assertEqual(self.client.post('/api/read-all',headers={'Origin':'https://example.com'}).status_code,403)
        self.assertEqual(self.client.put('/api/sources/cn-policy-laws',json={'paused':False,'hours':0}).status_code,422)

    def test_source_registry_valid_ids(self):
        sources=json.loads((db.ROOT/'config/sources.json').read_text(encoding='utf-8'))
        self.assertEqual(len({s['id'] for s in sources}),len(sources))
        self.assertIsNone(collectors.official_url(sources[0]['url'],'http://127.0.0.1/private'))

    def test_non_utf8_corrupt_title_is_explicit(self):
        obj=collectors.cn_payload(b'{"show":1,"pageInfo":{"rows":[{"title":"bad\xff","url":"/article/test.html"}]}}')
        self.assertIn('\ufffd',obj['pageInfo']['rows'][0]['title'])

    def test_binary_attachment_hash_and_download(self):
        parent=self.seed()
        with db.connection() as c:
            aid,_=db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/test.xlsx','title':'附件.xlsx','kind':'attachment','parent_id':parent},True)
            article=dict(c.execute('SELECT * FROM articles WHERE id=?',(aid,)).fetchone())|{'hours':6}
        for content in [b'first bytes',b'first bytes',b'changed bytes']:
            with db.connection() as c:
                c.execute('DELETE FROM file_checks WHERE article_id=?',(aid,))
            with patch.object(collectors,'fetch',return_value=(content,'application/octet-stream')):
                service.sync_file(article)
        with db.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM versions WHERE article_id=?',(aid,)).fetchone()[0],2)
        self.assertEqual(self.client.get('/api/attachments/'+aid+'/download').content,b'changed bytes')
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['unread'],1)

    def test_extract_official_title_without_executing_script(self):
        html="<script>var title = '商务部公告'; var another = malicious();</script>".encode()
        self.assertEqual(collectors.article_title(html),'商务部公告')
        self.assertTrue(collectors.bad_title('????????????????'))
        self.assertFalse(collectors.bad_title('如何申请出口许可证？'))

    def test_cn_list_preserves_official_subtitle(self):
        source=next(x for x in json.loads((db.ROOT/'config/sources.json').read_text(encoding='utf-8')) if x['id']=='cn-policy-laws')
        body=json.dumps({'show':1,'pageInfo':{'total':1,'maxPageNum':1,'rows':[{'title':'中华人民共和国出口管制法','subTitle':'（2020年10月17日通过）','url':'/article/226.html'}]}}).encode()
        with patch.object(collectors,'fetch',return_value=(body,'application/json')):
            records,_,_=collectors.discover(source)
        self.assertEqual(records[0]['title'],'中华人民共和国出口管制法')
        self.assertEqual(records[0]['description'],'（2020年10月17日通过）')

    def test_verified_title_not_replaced_by_bad_list_title(self):
        aid=self.seed()
        with db.connection() as c:
            db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/article/test.html','title':'官方文章 · test'},True)
            self.assertEqual(c.execute('SELECT title FROM articles WHERE id=?',(aid,)).fetchone()[0],'受控测试公告')

    def test_title_hydration_is_independent_from_snapshot_registration(self):
        with db.connection() as c:
            aid,_=db.add_article(c,'cn-policy-regulations',{'url':'https://exportcontrol.mofcom.gov.cn/article/1269.html','title':'官方文章 · 1269'},True)
            article=dict(c.execute('SELECT * FROM ('+db.SCOPED_ARTICLES+') WHERE id=?',(aid,)).fetchone())
        html="<script>var title = '实施《中华人民共和国反外国制裁法》的规定';</script>".encode()
        service.title_jobs.add(aid)
        with patch.object(collectors,'fetch',return_value=(html,'text/html')):
            service.hydrate_title(article)
        with db.connection() as c:
            row=c.execute('SELECT title,description,error,watch_id FROM articles WHERE id=?',(aid,)).fetchone()
            self.assertEqual(row['title'],'实施《中华人民共和国反外国制裁法》的规定')
            self.assertEqual(row['description'],'');self.assertEqual(row['error'],'')
            self.assertIsNone(row['watch_id'])
            self.assertFalse(c.execute('SELECT 1 FROM metadata WHERE key=?',('title-retry:'+aid,)).fetchone())

    def test_title_hydration_failure_uses_backoff(self):
        with db.connection() as c:
            aid,_=db.add_article(c,'cn-policy-regulations',{'url':'https://exportcontrol.mofcom.gov.cn/article/844.html','title':'官方文章 · 844'},True)
            article=dict(c.execute('SELECT * FROM ('+db.SCOPED_ARTICLES+') WHERE id=?',(aid,)).fetchone())
        service.title_jobs.add(aid)
        with patch.object(collectors,'fetch',side_effect=collectors.httpx.ConnectError('temporary disconnect')):
            service.hydrate_title(article)
        with db.connection() as c:
            self.assertTrue(c.execute('SELECT 1 FROM metadata WHERE key=?',('title-retry:'+aid,)).fetchone())
            self.assertIn('标题核实未完成',c.execute('SELECT error FROM articles WHERE id=?',(aid,)).fetchone()[0])

    def test_pdf_subprocess_preserves_chinese_extraction_notice(self):
        from pypdf import PdfWriter
        buffer=io.BytesIO();writer=PdfWriter();writer.add_blank_page(width=100,height=100);writer.write(buffer)
        parent=self.seed()
        with db.connection() as c:
            aid,_=db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/test.pdf','title':'测试 PDF','kind':'attachment','parent_id':parent},True)
            article=dict(c.execute('SELECT * FROM articles WHERE id=?',(aid,)).fetchone())|{'hours':6}
        with patch.object(collectors,'fetch',return_value=(buffer.getvalue(),'application/pdf')):
            service.sync_file(article)
        with db.connection() as c:
            content=c.execute('SELECT content FROM versions WHERE article_id=?',(aid,)).fetchone()[0]
            self.assertIn('无可提取文本',content)

    def test_one_article_can_belong_to_two_official_categories(self):
        aid=self.seed()
        with db.connection() as c:
            other,fresh=db.add_article(c,'cn-policy-regulations',{'url':'https://exportcontrol.mofcom.gov.cn/article/test.html','title':'受控测试公告'},False)
            self.assertEqual(other,aid);self.assertFalse(fresh)
            self.assertEqual(c.execute('SELECT count(*) FROM articles').fetchone()[0],1)
        self.assertEqual(self.client.get('/api/articles').json()['total'],1)
        for cat in ['cn-domestic-laws','cn-domestic-regulations']:
            self.assertEqual(self.client.get('/api/articles?category='+cat).json()['items'][0]['id'],aid)
        self.assertEqual({x['category_name'] for x in self.client.get('/api/articles/'+aid).json()['locations']},{'法律','法规'})
        self.assertEqual(self.client.get('/api/dashboard').json()['stats']['unread'],0)

    def test_shared_attachment_relation_uses_all_parents(self):
        aid=self.seed()
        with db.connection() as c:
            second,_=db.add_article(c,'cn-policy-rules',{'url':'https://exportcontrol.mofcom.gov.cn/second.html','title':'第二篇'},True)
            item={'url':'https://exportcontrol.mofcom.gov.cn/shared.pdf','title':'共享附件','kind':'attachment','parent_id':aid}
            file1,_=db.add_article(c,'cn-policy-laws',item,True)
            file2,_=db.add_article(c,'cn-policy-rules',item|{'parent_id':second},True)
            self.assertEqual(file1,file2)
        for parent in [aid,second]:
            self.assertEqual(self.client.get('/api/articles/'+parent).json()['attachments'][0]['id'],file1)

    def test_only_five_china_sources_and_foreign_keys_enforced(self):
        data=self.client.get('/api/dashboard').json()
        self.assertEqual(len(data['sources']),5)
        self.assertEqual({s['external_code'] for s in data['sources']},{'1','2','13','14','15'})
        self.assertEqual({s['country_code'] for s in data['sources']},{'CN'})
        self.assertEqual({s['role'] for s in data['sources']},{'primary','secondary'})
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connection() as c:c.execute("INSERT INTO article_sources VALUES('absent','cn-policy-laws',1,1,NULL,NULL)")

    def test_active_source_requires_explicit_data_scope(self):
        import sqlite3
        with self.assertRaises(sqlite3.IntegrityError):
            with db.connection() as c:
                c.execute("INSERT INTO sources(id,config,publisher_id,category_id,in_scope,name) VALUES('bad','{}','cn-exportcontrol','cn-domestic-laws',1,'bad')")

    def test_full_pagination_and_audit_counts(self):
        source=next(x for x in json.loads((db.ROOT/'config/sources.json').read_text(encoding='utf-8')) if x['id']=='cn-policy-rules')
        def response(url,data=None):
            page=data['pageNumber'];rows=[{'title':'公告 '+str(page),'url':'/article/'+str(page)+'.html','id':str(page)}]
            return json.dumps({'show':1,'pageInfo':{'pageNumber':page,'maxPageNum':4,'total':4,'rows':rows}}).encode(), 'application/json'
        with patch.object(collectors,'fetch',side_effect=response):
            records,coverage,pages=collectors.discover(source)
            self.assertEqual(len(records),4);self.assertEqual(len(pages),4)
            self.assertEqual(records[-1]['source_page'],4)
            self.assertEqual([x['source_position'] for x in records],[1,2,3,4])
            self.assertIn('全部列表',coverage)
            service.run_source('cn-policy-rules')
        with db.connection() as c:
            self.assertEqual(c.execute('SELECT count(*) FROM crawl_pages').fetchone()[0],4)
            self.assertEqual(c.execute('SELECT count(*) FROM article_sources WHERE source_page=4').fetchone()[0],1)

    def test_category_view_uses_official_source_order(self):
        with db.connection() as c:
            second,_=db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/second.html','title':'官网第二条','published':'2030-01-01','external_id':'second','source_position':2},True)
            first,_=db.add_article(c,'cn-policy-laws',{'url':'https://exportcontrol.mofcom.gov.cn/first.html','title':'官网第一条','published':'2020-01-01','external_id':'first','source_position':1},True)
        items=self.client.get('/api/articles?category=cn-domestic-laws').json()['items']
        self.assertEqual([x['id'] for x in items],[first,second])

    def test_primary_category_order_starts_with_rules(self):
        categories=[x for x in self.client.get('/api/taxonomy').json()['categories'] if x['role']=='primary']
        self.assertEqual([x['name'] for x in categories],['规章及规范性文件','法律','法规'])

    def test_paused_category_does_not_override_active_shared_article_interval(self):
        aid=self.seed()
        with db.connection() as c:
            db.add_article(c,'cn-policy-regulations',{'url':'https://exportcontrol.mofcom.gov.cn/article/test.html','title':'受控测试公告'},True)
            c.execute("UPDATE sources SET paused=1,hours=1 WHERE id='cn-policy-laws'")
            c.execute("UPDATE sources SET hours=24 WHERE id='cn-policy-regulations'")
            record=c.execute('SELECT * FROM ('+db.SCOPED_ARTICLES+') WHERE id=?',(aid,)).fetchone()
            self.assertEqual(record['hours'],24);self.assertEqual(record['paused'],0)

    def test_distinct_official_entries_same_url_preserve_both_identifiers(self):
        item={'url':'https://exportcontrol.mofcom.gov.cn/one.html','title':'同一公告','external_id':'official-a','source_page':2}
        with db.connection() as c:
            a,_=db.add_article(c,'cn-policy-rules',item,True)
            b,_=db.add_article(c,'cn-policy-rules',item|{'external_id':'official-b','source_page':3},True)
            self.assertEqual(a,b)
            self.assertEqual(c.execute('SELECT count(*) FROM source_entries').fetchone()[0],2)
            self.assertEqual(c.execute('SELECT count(*) FROM article_sources').fetchone()[0],1)
            self.assertEqual(c.execute('SELECT count(*) FROM articles').fetchone()[0],1)

    def test_transient_disconnect_retries_without_disabling_tls(self):
        import httpx
        import ssl
        with patch.object(collectors,'_fetch_once',side_effect=[httpx.RemoteProtocolError('disconnected'),(b'content','text/html')]) as fetch,patch.object(collectors.time,'sleep'):
            self.assertEqual(collectors.fetch('https://exportcontrol.mofcom.gov.cn/'),(b'content','text/html'))
            self.assertEqual(fetch.call_count,2)
        with patch.object(collectors,'_fetch_once',side_effect=[ssl.SSLEOFError('unexpected EOF'),(b'content','text/html')]) as fetch,patch.object(collectors.time,'sleep'):
            self.assertEqual(collectors.fetch('https://exportcontrol.mofcom.gov.cn/'),(b'content','text/html'))
            self.assertEqual(fetch.call_count,2)
        with patch.object(collectors,'_fetch_once',side_effect=httpx.ConnectError('certificate verify failed')) as fetch,patch.object(collectors.time,'sleep'):
            with self.assertRaises(httpx.ConnectError):collectors.fetch('https://exportcontrol.mofcom.gov.cn/')
            self.assertEqual(fetch.call_count,1)


if __name__=='__main__':unittest.main()
