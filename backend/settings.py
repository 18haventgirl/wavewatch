from dataclasses import dataclass, field
import os
import json
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str = field(repr=False)
    engine_url: str = ''
    engine_key: str = field(default='', repr=False)
    files_root: Path = Path(__file__).resolve().parents[1] / 'data-v2'
    wechat_appid: str = 'wxf4607c24eac40b2b'
    wechat_secret: str = field(default='', repr=False)
    session_seconds: int = 86400

    @classmethod
    def load(cls):
        url = os.environ.get('OBS_DATABASE_URL', '')
        if not url:
            raise RuntimeError('Set OBS_DATABASE_URL to an isolated V2 database')
        config = json.loads((Path(__file__).resolve().parents[1] / 'config' / 'wechat.json').read_text(encoding='utf-8'))
        return cls(url, os.environ.get('OBS_ADMIN_TOKEN', ''),
                   os.environ.get('OBS_ENGINE_URL', ''), os.environ.get('OBS_ENGINE_KEY', ''),
                   Path(os.environ.get('OBS_FILES_ROOT', str(cls.files_root))).resolve(),
                   os.environ.get('OBS_WECHAT_APPID', config['appid']),
                   os.environ.get('OBS_WECHAT_APP_SECRET', ''))
