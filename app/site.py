"""Adapter for 中国出口管制信息网 (exportcontrol.mofcom.gov.cn).

Two things are read from the site:
* the column list API (JSON, paginated) to discover entries;
* article pages, whose body lives in ``.u-art-box .bd`` and whose metadata is
  assigned as string literals in an inline script (read with a regex, never executed).
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from urllib.parse import unquote, urlsplit

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

from . import config, fetch

FILE_EXT = re.compile(r'\.(pdf|docx?|xlsx?|wps|et|ofd|zip|rar|7z|txt|csv)(?:\?|$)', re.I)
BLOCK_TAGS = {'p', 'div', 'li', 'ul', 'ol', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'section', 'article',
              'blockquote', 'pre', 'dl', 'dt', 'dd', 'center', 'tr', 'tbody', 'thead', 'figure', 'figcaption'}
SCRIPT_VAR = re.compile(r'''\bvar\s+(\w+)\s*=\s*('(?:\\.|[^'\\])*'|"(?:\\.|[^"\\])*")''')


@dataclass
class ListItem:
    url: str
    title: str
    subtitle: str
    published: str | None
    external_key: str
    raw_title: str
    page: int
    position: int

    @property
    def title_ok(self) -> bool:
        return not bad_title(self.title)


@dataclass
class ListPage:
    page: int
    items: list[ListItem]
    total: int
    max_page: int
    digest: str
    skipped: int = 0


@dataclass
class ArticlePage:
    title: str | None
    subtitle: str
    origin: str
    published: str | None
    text: str
    attachments: list[tuple[str, str]] = field(default_factory=list)


class ParseError(Exception):
    pass


# --- helpers --------------------------------------------------------------------

def article_id(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:24]


def bad_title(title: str | None) -> bool:
    """Titles damaged by the list API's encoding problems (literal '?' or U+FFFD)."""
    if not title or not title.strip():
        return True
    return '�' in title or title.count('?') > max(3, len(title) // 4) or title.startswith('官方文章 · ')


def clean_line(text: str) -> str:
    return re.sub(r'\s+', ' ', text.replace('　', ' ').replace('\xa0', ' ')).strip()


def placeholder_title(url: str) -> str:
    return '官方文章 · ' + urlsplit(url).path.rsplit('/', 1)[-1].removesuffix('.html')


# --- list API -----------------------------------------------------------------------

def fetch_list_page(column_id: int, page: int) -> ListPage:
    resp = fetch.get(config.LIST_API, data={'pageNumber': page, 'columnID': column_id, 'title': ''}, accept_json=True)
    return parse_list_page(resp.body, page, column_id)


def parse_list_page(body: bytes, page: int, column_id: int) -> ListPage:
    text = body.decode('utf-8', errors='replace')
    try:
        obj = json.loads(text, strict=False)
    except ValueError as exc:
        if fetch.looks_like_challenge(text):
            raise ParseError('原站返回访问验证页面，未取得列表') from exc
        raise ParseError('栏目接口没有返回有效 JSON') from exc
    info = obj.get('pageInfo') if isinstance(obj, dict) else None
    if not isinstance(info, dict) or str(obj.get('show')) != '1' or not isinstance(info.get('rows'), list):
        raise ParseError('栏目接口格式与预期不符，可能已改版')
    if int(info.get('pageNumber') or page) != page:
        raise ParseError('原站返回的页码与请求不一致')
    base = config.source_page_url(column_id)
    items, skipped = [], 0
    for index, entry in enumerate(info['rows'], start=1):
        raw_title = str(entry.get('title') or '').strip()
        url = fetch.official_url(base, str(entry.get('url') or ''))
        if not url:
            skipped += 1
            continue
        subtitle = clean_line(str(entry.get('subTitle') or ''))
        title = raw_title if not bad_title(raw_title) else placeholder_title(url)
        items.append(ListItem(
            url=url, title=title, subtitle='' if bad_title(subtitle) else subtitle,
            published=str(entry.get('publishTimeStr') or '').strip() or None,
            external_key=str(entry.get('id') or entry.get('cuid') or entry.get('articleId') or url),
            raw_title=raw_title, page=page, position=(page - 1) * 1000 + index))
    return ListPage(page=page, items=items, total=int(info.get('total') or 0),
                    max_page=int(info.get('maxPageNum') or 1), digest=hashlib.sha256(body).hexdigest(), skipped=skipped)


# --- article pages ------------------------------------------------------------------

def script_vars(soup: BeautifulSoup) -> dict[str, str]:
    found: dict[str, str] = {}
    for script in soup.find_all('script'):
        for name, literal in SCRIPT_VAR.findall(script.get_text()):
            inner = literal[1:-1]
            # Undo JS string escapes without evaluating anything.
            value = re.sub(r'\\(.)', lambda m: {'n': '\n', 't': '\t'}.get(m.group(1), m.group(1)), inner)
            found.setdefault(name, value.strip())
    return found


def _render(node: Tag, parts: list[str]) -> None:
    for child in node.children:
        if isinstance(child, Comment):
            continue
        if isinstance(child, NavigableString):
            parts.append(str(child))
            continue
        if not isinstance(child, Tag):
            continue
        name = child.name
        if name in ('script', 'style', 'noscript', 'template'):
            continue
        if name == 'br':
            parts.append('\n')
        elif name == 'img':
            src = unquote(urlsplit(child.get('src') or '').path.rsplit('/', 1)[-1])
            alt = clean_line(child.get('alt') or '')
            parts.append(f"\n[图片] {alt or src or '无文件名'}\n")
        elif name == 'table':
            for tr in child.find_all('tr'):
                cells = [clean_line(cell.get_text(' ')) for cell in tr.find_all(['td', 'th'], recursive=False)]
                if any(cells):
                    parts.append('\n' + ' | '.join(cells) + '\n')
        else:
            block = name in BLOCK_TAGS
            if block:
                parts.append('\n')
            _render(child, parts)
            if block:
                parts.append('\n')


def body_text(node: Tag) -> str:
    """Readable, stable text: one paragraph per line, whitespace normalised."""
    parts: list[str] = []
    _render(node, parts)
    lines = (clean_line(line) for line in ''.join(parts).split('\n'))
    return '\n'.join(line for line in lines if line)


def parse_article(html: bytes | str, url: str) -> ArticlePage:
    soup = BeautifulSoup(html, 'html.parser')
    box = soup.select_one('.u-art-box')
    if box is None:
        text = soup.get_text(' ', strip=True)
        if fetch.looks_like_challenge(text):
            raise ParseError('原站返回访问验证页面')
        raise ParseError('页面中没有找到文章正文区域，可能已改版或文章已撤下')
    meta = script_vars(soup)
    body = box.select_one('.bd') or box
    text = body_text(body)
    heading = box.select_one('#show_title, h3.u-tt, h1')
    title = meta.get('title') or (clean_line(heading.get_text(' ')) if heading else '')
    attachments: dict[str, str] = {}
    for anchor in box.select('a[href]'):
        link = fetch.official_url(url, anchor.get('href', ''))
        if link and FILE_EXT.search(link) and link != url:
            name = clean_line(anchor.get_text(' ')) or unquote(urlsplit(link).path.rsplit('/', 1)[-1])
            attachments.setdefault(link, name)
    if not text and not attachments:
        raise ParseError('正文区域为空，暂不作为有效版本保存')
    return ArticlePage(
        title=title if title and not bad_title(title) else None,
        subtitle=clean_line(meta.get('subTitle', '')),
        origin=clean_line(meta.get('source', '')),
        published=meta.get('publishTime') or None,
        text=text or '（正文仅包含附件）',
        attachments=list(attachments.items()))
