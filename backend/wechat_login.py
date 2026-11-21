"""No URL-logging transport: the official GET query contains credentials."""
import http.client
import json
import ssl
from urllib.parse import urlencode
import truststore
from fastapi import HTTPException


class WeChatLogin:
    def __init__(self, settings):
        self.settings = settings

    def exchange(self, code):
        if not self.settings.wechat_appid or not self.settings.wechat_secret:
            raise HTTPException(503, '尚未在服务端配置微信登录密钥')
        query = urlencode(dict(appid=self.settings.wechat_appid, secret=self.settings.wechat_secret,
                               js_code=code, grant_type='authorization_code'))
        connection = http.client.HTTPSConnection('api.weixin.qq.com', timeout=15,
            context=truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT))
        try:
            connection.request('GET', '/sns/jscode2session?' + query)
            response = connection.getresponse()
            body = response.read(32 * 1024 + 1)
            if response.status != 200 or len(body) > 32 * 1024:
                raise ValueError('invalid response')
            data = json.loads(body)
        except Exception:
            raise HTTPException(502, '微信登录服务暂不可用，请重新登录') from None
        finally:
            connection.close()
        if not isinstance(data, dict) or data.get('errcode', 0):
            raise HTTPException(401, '微信登录凭证未通过验证，请重新登录')
        openid = data.get('openid')
        if not isinstance(openid, str) or not 1 <= len(openid) <= 128 or not data.get('session_key'):
            raise HTTPException(502, '微信返回的身份信息不完整')
        # No phone/profile permission is requested. session_key is not needed by this
        # product and is neither returned to the client nor persisted.
        return openid
