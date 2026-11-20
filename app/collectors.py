from __future__ import annotations
import json
import ast
import hashlib
import time
import re
import ssl
from urllib.parse import urljoin, urlsplit, urlunsplit
import xml.etree.ElementTree as ET
import httpx
import truststore
from bs4 import BeautifulSoup

ALLOWED = {'exportcontrol.mofcom.gov.cn','www.mofcom.gov.cn','www.bis.gov','www.trade.gov',
           'www.federalregister.gov','www.govinfo.gov','www.bafa.de','www.sanctionsmap.eu',
           'sanctionsmap.eu','eur-lex.europa.eu'}
TLS = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)


def official_url(base, link):
    url = urljoin(base,link)
    parts = urlsplit(url)
    if parts.hostname not in ALLOWED or parts.scheme not in ('http','https') or parts.username:
        return None
    return urlunsplit(('https',parts.netloc,parts.path,parts.query,''))


def fetch(url, data=None):
    # These are idempotent GETs or the official read-only list query POST.
    # Retry transient disconnects a bounded number of times, never bypass TLS.
    for attempt in range(3):
        try:return _fetch_once(url,data)
        except (httpx.TransportError,ssl.SSLError) as exc:
            if attempt==2 or 'certificate' in str(exc).lower():raise
            time.sleep(2**attempt)


def _fetch_once(url, data=None):
    if not official_url(url,url):
        raise ValueError('链接不在已核实的官方来源范围内')
    with httpx.Client(verify=TLS,timeout=30,follow_redirects=False,headers={'User-Agent':'ExportObservatory/0.1 (personal publication monitor)'}) as client:
        for _ in range(6):
            # The official list endpoint emits damaged Chinese fields for */*.
            # Match the page's JSON content negotiation while retaining our identity.
            headers={'Accept':'application/json, text/javascript, */*; q=0.01'} if data else {}
            with client.stream('POST' if data else 'GET',url,data=data,headers=headers) as response:
                if response.is_redirect:
                    target=official_url(url,response.headers.get('location',''))
                    if not target:
                        raise ValueError('重定向至未核实来源，已停止')
                    url,data=target,None
                    continue
                response.raise_for_status()
                chunks=[]
                size=0
                for chunk in response.iter_bytes():
                    size+=len(chunk)
                    if size>25*1024*1024:
                        raise ValueError('文件超过 25 MB，尚未处理')
                    chunks.append(chunk)
                return b''.join(chunks),response.headers.get('content-type','')
    raise ValueError('重定向次数过多')


def soup_of(body):
    soup=BeautifulSoup(body,'html.parser')
    for node in soup(['script','style','noscript','nav','footer','header']):
        node.decompose()
    text=soup.get_text(' ',strip=True)
    if any(x in text[:1200].lower() for x in ('just a moment','verify you are human','access denied','please wait','captcha')):
        raise ValueError('原站返回访问挑战内容，尚未通过采集验证')
    return soup


def cn_payload(body):
    # Some legacy responses contain invalid UTF-8 bytes. Retain valid records and
    # report/skips corrupted titles rather than silently publishing replacements.
    text=body.decode('utf-8',errors='replace')
    obj=json.loads(text,strict=False)
    if not isinstance(obj,dict) or str(obj.get('show'))!='1' or not isinstance(obj.get('pageInfo',{}).get('rows'),list):
        raise ValueError('栏目接口格式与预期不符')
    return obj


def article_title(body):
    soup=BeautifulSoup(body,'html.parser')
    # Read a string literal only. Never execute script code from a source page.
    for script in soup.select('script'):
        match=re.search(r'''\bvar\s+title\s*=\s*('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")''',script.get_text())
        if match:
            try:
                title=ast.literal_eval(match.group(1))
                if isinstance(title,str) and title.strip():return title.strip()
            except (ValueError,SyntaxError):pass
    heading=soup.select_one('#show_title, .u-art-box h3, main h1, article h1')
    return heading.get_text(' ',strip=True) if heading else None


def bad_title(title):
    return '\ufffd' in title or title.count('?')>max(3,len(title)//4) or title.startswith('官方文章 · ')


def discover(source):
    mode=source['mode']
    records=[]
    issues=[]
    page_audits=[]
    if mode=='cn_json':
        columns=source.get('columns',[source['form_data']['columnID']])
        for column_index,column in enumerate(columns):
            more=False
            ordinal=0
            page_limit=int(source.get('max_pages',100))
            for page in range(1,page_limit+1):
                data=source['form_data']|{'columnID':column,'pageNumber':page}
                body,_=fetch(source['fetch_url'],data)
                obj=cn_payload(body)
                rows=obj['pageInfo']['rows']
                info=obj['pageInfo']
                if int(info.get('pageNumber') or page)!=page:raise ValueError('原站返回的页码与请求不一致')
                page_audits.append({'page_number':page,'item_count':len(rows),'reported_total':int(info.get('total') or 0),'response_digest':hashlib.sha256(body).hexdigest(),'checked':time.time()})
                for row in rows:
                    ordinal+=1
                    title=str(row.get('title','')).strip()
                    url=official_url(source['url'],str(row.get('url','')))
                    if not title or not url:
                        issues.append('部分记录标题编码或来源地址异常，已保留覆盖提示')
                        continue
                    subtitle=str(row.get('subTitle') or '').strip()
                    description=subtitle if subtitle and not bad_title(subtitle) else ''
                    if bad_title(title):
                        issues.append('列表标题异常，正在以官方文章页核实')
                        title='官方文章 · '+urlsplit(url).path.rsplit('/',1)[-1].removesuffix('.html')
                        description='列表标题不可读，完整标题将在官方文章页核实后更新。'
                    records.append({'url':url,'title':title,'published':str(row.get('publishTimeStr') or '') or None,'description':description,'source_page':page,'source_position':column_index*1000000+ordinal,'raw_title':str(row.get('title','')),'external_id':str(row.get('id') or row.get('cuid') or row.get('articleId') or url)})
                more=page < int(obj['pageInfo'].get('maxPageNum') or 1)
                if not more:
                    break
            if more:
                issues.append(f'栏目 {column} 达到 {page_limit} 页上限，历史覆盖不完整')
        reported=page_audits[0]['reported_total'] if page_audits else 0
        valid_count=len({x['url'] for x in records})
        if len(records)!=reported:issues.append(f'原站报告 {reported} 条，本次有效列表条目 {len(records)} 条，需复核')
        duplicate_count=len(records)-valid_count
        coverage=f'已读取 {len(page_audits)} 页 / 原站报告 {reported} 条 / 去重文章 {valid_count} 篇；'
        if duplicate_count:coverage+=f'{duplicate_count} 条重复链接已保留来源条目；'
        coverage+=('；'.join(dict.fromkeys(issues)) or '已覆盖当前栏目全部列表')
    elif mode=='json':
        body,_=fetch(source['url'])
        obj=json.loads(body)
        for row in obj.get('results',[]):
            url=official_url(source['url'],row.get('html_url',''))
            if row.get('title') and row.get('document_number') and url:
                records.append({'url':url,'title':row['title'],'published':row.get('publication_date'),'description':row.get('abstract') or ''})
        coverage='补充来源：最近 20 份 BIS 法规文件；不是 BIS 主站接通状态'
    elif mode=='rss':
        body,_=fetch(source['url'])
        root=ET.fromstring(body)
        if root.tag not in ('rss','{http://www.w3.org/2005/Atom}feed'):
            raise ValueError('返回内容不是 RSS/Atom')
        for row in root.findall('.//item'):
            url=official_url(source['url'],row.findtext('link') or '')
            if url and row.findtext('title'):
                records.append({'url':url,'title':row.findtext('title'),'published':row.findtext('pubDate') or row.findtext('{http://purl.org/dc/elements/1.1/}date')})
        coverage='RSS 当前返回条目；不代表全部历史公告'
    elif mode=='browser':
        raise ValueError('EU Sanctions Map 需要浏览器采集；尚未验证内容，未标为接通')
    else:
        body,_=fetch(source['url'])
        soup=soup_of(body)
        main=soup.select_one(source.get('selector','main'))
        if not main or len(main.get_text(strip=True))<100:
            raise ValueError('未找到足够的正文内容')
        if source['id'] in ('us-guide','us-bis-rules'):
            title='U.S. Export Controls · 官方介绍' if source['id']=='us-guide' else 'BIS · Federal Register Notices 入口页'
            records=[{'url':source['url'],'title':title,'description':'入口页正文监测；法规文件由单独标记的补充来源收录'}]
        else:
            for anchor in main.select('a[href]'):
                url=official_url(source['url'],anchor.get('href',''))
                title=anchor.get_text(' ',strip=True)
                if not url or len(title)<16 or url==source['url']:
                    continue
                path=urlsplit(url).path
                if source['id']=='us-bis-news' and not any(x in path for x in ('/press-release/','/news-updates/')):
                    continue
                if source['id']=='us-bis-rules' and not any(x in path for x in ('/documents/','/regulations/')):
                    continue
                records.append({'url':url,'title':title})
        coverage='当前入口展示的链接；未遍历所有历史分页'
    unique={x['url']:x for x in records}
    if not unique:
        raise ValueError('未解析出有效条目，保留历史数据，等待复核')
    return (records if mode=='cn_json' else list(unique.values())),coverage,page_audits


def attachments(article_url, body):
    soup=soup_of(body)
    main=soup.select_one('main, .u-art-box, .art-con, .article-content, .TRS_Editor, .u-article-content') or soup
    found={}
    for a in main.select('a[href]'):
        url=official_url(article_url,a.get('href',''))
        if url and re.search(r'\.(pdf|docx?|xlsx?|zip)(?:\?|$)',url,re.I):
            found[url]={'url':url,'title':a.get_text(' ',strip=True) or urlsplit(url).path.rsplit('/',1)[-1],'kind':'attachment'}
    return list(found.values())
