from dataclasses import dataclass
import os
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str
    engine_url: str = ''
    engine_key: str = ''
    files_root: Path = Path(__file__).resolve().parents[1] / 'data-v2'

    @classmethod
    def load(cls):
        url = os.environ.get('OBS_DATABASE_URL', '')
        if not url:
            raise RuntimeError('Set OBS_DATABASE_URL to an isolated V2 database')
        return cls(url, os.environ.get('OBS_ADMIN_TOKEN', ''),
                   os.environ.get('OBS_ENGINE_URL', ''), os.environ.get('OBS_ENGINE_KEY', ''),
                   Path(os.environ.get('OBS_FILES_ROOT', str(cls.files_root))).resolve())
