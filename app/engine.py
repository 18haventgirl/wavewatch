"""REST adapter for the unmodified changedetection.io service."""
from __future__ import annotations
import json
import os
import httpx
from . import db
from .db import DATA

BASE = os.getenv('CHANGEDETECTION_URL','http://127.0.0.1:8841').rstrip('/')


def prepare_local_scope():
    """Apply scope while the upstream engine is stopped, before any fetcher starts.

    Uses the pinned upstream store's atomic Watch.commit(), never edits its code.
    Archived snapshots remain on disk; only their scheduling is paused.
    """
    if not (DATA/'engine'/'changedetection.json').exists():return
    from changedetectionio.store import ChangeDetectionStore
    from loguru import logger
    logger.disable('changedetectionio')
    store=ChangeDetectionStore(datastore_path=str(DATA/'engine'),include_default_watches=False,version_tag='0.70.4')
    with db.connection() as conn:
        desired={r['watch_id']:r['hours'] for r in conn.execute('SELECT watch_id,MIN(hours) AS hours FROM ('+db.SCOPED_ARTICLES+') WHERE paused=0 AND watch_id IS NOT NULL GROUP BY watch_id')}
    for wid,watch in store.data['watching'].items():
        paused=wid not in desired
        if watch.get('paused')!=paused:
            watch['paused']=paused
            watch.commit()
    logger.enable('changedetectionio')


def api(path, method='GET', payload=None):
    token = os.getenv('CHANGEDETECTION_API_KEY')
    if not token:
        for name in ('changedetection.json','url-watches.json'):
            file = DATA / 'engine' / name
            if file.exists():
                try:
                    token = json.loads(file.read_text(encoding='utf-8'))['settings']['application']['api_access_token']
                    break
                except (KeyError, ValueError, OSError):
                    pass
    if not token:
        raise RuntimeError('监测引擎尚未就绪')
    with httpx.Client(timeout=20, trust_env=False) as client:
        response = client.request(method, BASE + '/api/v1/' + path, headers={'x-api-key':token},json=payload)
        if response.is_error:
            raise RuntimeError(f'监测引擎返回 {response.status_code}，请查看本机运行日志')
        if not response.content:
            return None
        if 'json' in response.headers.get('content-type',''):
            return response.json()
        return response.text


def health():
    try:
        data = api('systeminfo')
        return {'online':True,'name':'changedetection.io','version': data.get('version', '0.70.4') if isinstance(data,dict) else '0.70.4'}
    except Exception as exc:
        return {'online':False,'name':'changedetection.io','error':str(exc)}


def filters_for(article):
    if article['kind']=='attachment':return []
    host=httpx.URL(article['url']).host
    if host=='exportcontrol.mofcom.gov.cn':return ['.u-art-box']
    if host in ('www.bis.gov','www.trade.gov','www.federalregister.gov'):return ['main']
    if host=='www.bafa.de':return ['main, #main']
    return []


def register(article, hours, paused=False):
    existing = api('watch')
    # Reconcile by URL after a crash between upstream creation and local commit.
    for wid, watch in existing.items():
        if watch.get('url') == article['url']:
            return wid
    payload = {'url':article['url'],'title':article['title'],'fetch_backend':'html_requests',
               'time_between_check':{'hours':hours},'time_between_check_use_default':False,
               'paused':bool(paused),'tag':'观澜文章', 'notification_muted':True}
    if filters_for(article):payload['include_filters']=filters_for(article)
    result = api('watch','POST',payload)
    if isinstance(result,dict) and result.get('uuid'):
        return result['uuid']
    for wid, watch in api('watch').items():
        if watch.get('url') == article['url']:
            return wid
    raise RuntimeError('引擎创建监测任务后未返回任务标识')
