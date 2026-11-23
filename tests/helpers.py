"""Test fixtures: an isolated data directory and a fake official site."""
from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from app import config, db, fetch


def list_body(rows: list[dict], page: int = 1, total: int | None = None, max_page: int = 1) -> bytes:
    return json.dumps({'show': '1', 'pageInfo': {
        'rows': rows, 'pageNumber': page, 'total': len(rows) if total is None else total, 'maxPageNum': max_page,
    }}, ensure_ascii=False).encode()


def row(n: int, title: str | None = None, date: str = '2026-11-20 10:00:00', path: str | None = None) -> dict:
    return {'id': str(n), 'title': title or f'公告 {n}', 'url': path or f'/article/zcfg/{n}.html',
            'publishTimeStr': date, 'subTitle': ''}


def article_html(title: str, paragraphs: list[str], attachments: list[tuple[str, str]] = (), source: str = '商务部') -> str:
    body = ''.join(f'<p>　　{p}</p>' for p in paragraphs)
    links = ''.join(f'<p><a href="{href}">{name}</a></p>' for href, name in attachments)
    return f'''<html><head><title>中国出口管制信息网</title></head><body><nav>导航</nav>
<div class="u-art-box"><div class="hd"><h3 class="u-tt" id="show_title"></h3></div>
<div class="bd"><script>var title = '{title}'; var subTitle = ''; var source = '{source}';
var publishTime = '2026-11-20 10:00:00';</script>{body}{links}</div>
<div class="u-disclaimer-box">免责声明：本站转载……</div></div></body></html>'''


class FakeSite:
    """Routes fetch.get calls to in-memory pages."""

    def __init__(self):
        self.lists: dict[tuple[int, int], bytes] = {}
        self.pages: dict[str, tuple[bytes, str]] = {}
        self.fail: dict[str, Exception] = {}
        self.calls: list[str] = []

    def set_list(self, column: int, rows: list[dict], per_page: int = 20) -> None:
        pages = [rows[i:i + per_page] for i in range(0, len(rows), per_page)] or [[]]
        self.lists = {k: v for k, v in self.lists.items() if k[0] != column}
        for index, chunk in enumerate(pages, start=1):
            self.lists[(column, index)] = list_body(chunk, index, len(rows), len(pages))

    def set_page(self, path: str, html: str) -> None:
        self.pages['https://exportcontrol.mofcom.gov.cn' + path] = (html.encode(), 'text/html; charset=utf-8')

    def set_file(self, path: str, body: bytes, ctype: str = 'application/pdf') -> None:
        self.pages['https://exportcontrol.mofcom.gov.cn' + path] = (body, ctype)

    def get(self, url: str, data: dict | None = None, accept_json: bool = False, attempts: int = 3) -> fetch.Response:
        self.calls.append(url if not data else f"list:{data['columnID']}:{data['pageNumber']}")
        if url in self.fail:
            raise self.fail[url]
        if data:
            key = (int(data['columnID']), int(data['pageNumber']))
            if 'list' in self.fail:
                raise self.fail['list']
            return fetch.Response(url, self.lists.get(key, list_body([], key[1], 0, 1)), 'application/json')
        if url not in self.pages:
            raise fetch.FetchError('原站返回 HTTP 404')
        body, ctype = self.pages[url]
        return fetch.Response(url, body, ctype)


class DataTestCase(unittest.TestCase):
    """Every test gets its own empty data directory and fake site."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix='guanlan-test-'))
        self._saved = {k: getattr(config, k) for k in ('DATA', 'DB_PATH', 'LEGACY_DB_PATH', 'FILES', 'LOGS', 'REQUEST_SPACING')}
        config.DATA = self.tmp
        config.DB_PATH = self.tmp / 'guanlan.sqlite3'
        config.LEGACY_DB_PATH = self.tmp / 'observatory.sqlite3'
        config.FILES = self.tmp / 'files'
        config.LOGS = self.tmp / 'logs'
        config.REQUEST_SPACING = 0
        self.site = FakeSite()
        self._real_get = fetch.get
        fetch.get = self.site.get
        db.init()

    def tearDown(self):
        fetch.get = self._real_get
        for key, value in self._saved.items():
            setattr(config, key, value)
        shutil.rmtree(self.tmp, ignore_errors=True)

    # convenience
    def q(self, sql: str, args=()):
        with db.tx() as conn:
            return db.rows(conn, sql, args)

    def one(self, sql: str, args=()):
        with db.tx() as conn:
            return conn.execute(sql, args).fetchone()[0]
