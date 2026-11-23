"""HTTP access to the official site.

* Only verified official hosts; redirects are re-checked against the list.
* TLS is verified with the operating-system trust store (truststore), never disabled.
* Requests to one host are spaced out so frequent checks stay polite.
* Transient network failures are retried a bounded number of times.
"""
from __future__ import annotations

import ssl
import threading
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit, urlunsplit

import httpx
import truststore

from . import config

_TLS = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
_pace_lock = threading.Lock()
_last_request: dict[str, float] = {}

CHALLENGE_MARKERS = ('just a moment', 'verify you are human', 'access denied', 'please wait', 'captcha', '安全验证', '访问验证')


class FetchError(Exception):
    """A failure that is safe to show to the user (already in Chinese)."""


@dataclass
class Response:
    url: str
    body: bytes
    content_type: str

    @property
    def is_html(self) -> bool:
        return 'html' in self.content_type.lower() or self.body.lstrip()[:15].lower().startswith((b'<!doctype', b'<html'))


def official_url(base: str, link: str) -> str | None:
    """Absolute https URL on an allowed host, or None."""
    if not link or link.startswith(('javascript:', 'mailto:', '#')):
        return None
    parts = urlsplit(urljoin(base, link.strip()))
    if parts.scheme not in ('http', 'https') or parts.hostname not in config.ALLOWED_HOSTS or parts.username:
        return None
    return urlunsplit(('https', parts.netloc, parts.path, parts.query, ''))


def _pace(host: str) -> None:
    with _pace_lock:
        wait = _last_request.get(host, 0) + config.REQUEST_SPACING - time.monotonic()
        if wait > 0:
            time.sleep(wait)
        _last_request[host] = time.monotonic()


def _client() -> httpx.Client:
    return httpx.Client(verify=_TLS, timeout=httpx.Timeout(30, connect=15), follow_redirects=False,
                        headers={'User-Agent': config.USER_AGENT, 'Accept-Language': 'zh-CN,zh;q=0.9'})


def _once(url: str, data: dict | None, accept_json: bool) -> Response:
    with _client() as client:
        for _ in range(6):
            _pace(urlsplit(url).hostname or '')
            headers = {'Accept': 'application/json, text/javascript, */*; q=0.01'} if accept_json else {}
            # The official list endpoint returns damaged Chinese unless JSON is requested.
            with client.stream('POST' if data else 'GET', url, data=data, headers=headers) as resp:
                if resp.is_redirect:
                    target = official_url(url, resp.headers.get('location', ''))
                    if not target:
                        raise FetchError('原站重定向到未核实的地址，已停止')
                    url, data = target, None
                    continue
                if resp.status_code >= 400:
                    raise FetchError(f'原站返回 HTTP {resp.status_code}')
                chunks, size = [], 0
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > config.MAX_DOWNLOAD:
                        raise FetchError('文件超过 25 MB，未下载')
                    chunks.append(chunk)
                return Response(url, b''.join(chunks), resp.headers.get('content-type', ''))
    raise FetchError('重定向次数过多')


def get(url: str, data: dict | None = None, accept_json: bool = False, attempts: int = 3) -> Response:
    if not official_url(url, url):
        raise FetchError('地址不在已核实的官方站点范围内')
    for attempt in range(attempts):
        try:
            return _once(url, data, accept_json)
        except FetchError as exc:
            # 5xx can be transient; 4xx is not.
            if attempt == attempts - 1 or not str(exc).startswith('原站返回 HTTP 5'):
                raise
        except (httpx.TransportError, ssl.SSLError) as exc:
            if attempt == attempts - 1 or 'certificate' in str(exc).lower():
                raise FetchError(describe(exc)) from exc
        time.sleep(2 ** attempt * 2)
    raise FetchError('请求失败')  # pragma: no cover


def describe(exc: BaseException) -> str:
    """Turn any exception into a short Chinese explanation."""
    if isinstance(exc, FetchError):
        return str(exc)
    message = str(exc)
    lowered = message.lower()
    if 'certificate' in lowered:
        return '证书校验失败（未关闭安全校验），请检查本机网络或代理'
    if isinstance(exc, httpx.TimeoutException) or 'timed out' in lowered:
        return '连接原站超时，稍后自动重试'
    if isinstance(exc, httpx.ConnectError):
        return '无法连接原站，请检查网络'
    if isinstance(exc, httpx.TransportError):
        return '与原站的连接中断，稍后自动重试'
    return (message or exc.__class__.__name__)[:300]


def looks_like_challenge(text: str) -> bool:
    head = text[:1500].lower()
    return any(marker in head for marker in CHALLENGE_MARKERS)
