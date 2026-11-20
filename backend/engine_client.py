"""Explicitly configured server engine; never reads the legacy engine's secrets."""
from urllib.parse import quote, urlsplit
import httpx


class EngineHTTPError(RuntimeError):
    def __init__(self, status):
        self.status = status
        super().__init__(f'Monitor engine HTTP {status}')


class EngineClient:
    def __init__(self, settings):
        if not settings.engine_url or not settings.engine_key:
            raise RuntimeError('Configure the isolated V2 engine URL and API key')
        parts = urlsplit(settings.engine_url)
        if parts.scheme not in ('http', 'https') or parts.username or parts.query or parts.fragment:
            raise ValueError('Invalid engine URL')
        self.base = settings.engine_url.rstrip('/')
        self.key = settings.engine_key

    def api(self, path, method='GET', payload=None):
        with httpx.Client(timeout=30, trust_env=False, follow_redirects=False) as client:
            with client.stream(method, self.base + '/api/v1/' + path,
                               headers={'x-api-key': self.key}, json=payload) as response:
                # Never include engine credentials, payload or token-bearing URLs in errors.
                if response.is_error or response.is_redirect:
                    raise EngineHTTPError(response.status_code)
                chunks, size = [], 0
                for chunk in response.iter_bytes():
                    size += len(chunk)
                    if size > 8 * 1024 * 1024:
                        raise ValueError('Engine response exceeds synchronization limit')
                    chunks.append(chunk)
                body = b''.join(chunks)
                if not body:
                    return None
                if 'json' in response.headers.get('content-type', ''):
                    import json
                    return json.loads(body)
                return body.decode('utf-8')

    @staticmethod
    def path(wid, suffix=''):
        return 'watch/' + quote(str(wid), safe='') + suffix

    def ensure_watch(self, article, hours, paused=False):
        if article.get('watch_id'):
            try:
                existing_watch = self.api(self.path(article['watch_id']))
                if isinstance(existing_watch, dict) and existing_watch.get('url') == article['url']:
                    return article['watch_id']
            except EngineHTTPError as exc:
                if exc.status != 404:
                    raise
        existing = self.api('watch')
        if not isinstance(existing, dict):
            raise ValueError('Invalid engine watch list')
        # URL reconciliation also recovers a create-before-commit crash. A dedicated
        # V2 engine prevents adopting or changing unrelated applications' watches.
        for wid, watch in existing.items():
            if watch.get('url') == article['url']:
                return wid
        if paused:
            return None
        payload = dict(url=article['url'], title=article['title'], fetch_backend='html_requests',
                       time_between_check={'hours': hours}, time_between_check_use_default=False,
                       paused=False, notification_muted=True, tag='观澜V2', include_filters=['.u-art-box'])
        result = self.api('watch', 'POST', payload)
        if isinstance(result, dict) and result.get('uuid'):
            return result['uuid']
        for wid, watch in self.api('watch').items():
            if watch.get('url') == article['url']:
                return wid
        raise RuntimeError('Engine did not return a recoverable watch identifier')
