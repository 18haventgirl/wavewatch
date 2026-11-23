"""Paths and defaults shared by every module.

Timestamps are stored as UTC epoch seconds and shown in Beijing time.
"""
from __future__ import annotations

import json
import os
from datetime import timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('GUANLAN_DATA', ROOT / 'data'))
DB_PATH = DATA / 'guanlan.sqlite3'
LEGACY_DB_PATH = DATA / 'observatory.sqlite3'
FILES = DATA / 'files'
LOGS = Path(os.getenv('GUANLAN_LOGS', ROOT / 'logs'))
FRONTEND_DIST = ROOT / 'frontend' / 'dist'

HOST = '127.0.0.1'
PORT = int(os.getenv('GUANLAN_PORT', '8840'))
LOCAL_URL = f'http://{HOST}:{PORT}'

BEIJING = timezone(timedelta(hours=8))

SITE_HOME = 'https://exportcontrol.mofcom.gov.cn/'
LIST_API = 'https://exportcontrol.mofcom.gov.cn/edi_ecms_web_front/front/column/getColumnList'
ALLOWED_HOSTS = {'exportcontrol.mofcom.gov.cn'}
USER_AGENT = 'Guanlan/1.0 (personal export-control publication monitor)'

# Defaults; every value below can be changed per column in the UI.
DEFAULT_LIST_MINUTES = 5
DEFAULT_ARTICLE_HOURS = {'core': 6, 'news': 24}
DEFAULT_NOTIFY = {'core': 'instant', 'news': 'digest'}
FULL_SCAN_HOURS = 24          # complete pagination sweep to catch re-ordering and gaps
INCREMENTAL_MAX_PAGES = 5     # pages read per quick check while every row is still new
FULL_SCAN_MAX_PAGES = 100
REQUEST_SPACING = 1.2         # seconds between two requests to the official host
MAX_DOWNLOAD = 25 * 1024 * 1024
PDF_MAX_PAGES = 50
PDF_TIMEOUT = 25


def load_sources() -> list[dict]:
    return json.loads((ROOT / 'config' / 'sources.json').read_text(encoding='utf-8'))


def source_page_url(column_id: int) -> str:
    return f'{SITE_HOME}articleList.shtml?columnID={column_id}&num=1'
