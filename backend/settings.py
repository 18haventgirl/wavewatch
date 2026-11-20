from dataclasses import dataclass
import os


@dataclass(frozen=True)
class Settings:
    database_url: str
    admin_token: str

    @classmethod
    def load(cls):
        url = os.environ.get('OBS_DATABASE_URL', '')
        if not url:
            raise RuntimeError('Set OBS_DATABASE_URL to an isolated V2 database')
        return cls(url, os.environ.get('OBS_ADMIN_TOKEN', ''))
