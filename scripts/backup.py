"""Consistent backup that works while the monitor is running.

Uses SQLite's online backup API (safe with WAL) and copies saved attachment files.
Output: backups/guanlan-YYYYmmdd-HHMMSS.zip
"""
from __future__ import annotations

import datetime
import sqlite3
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def main() -> None:
    if not config.DB_PATH.exists():
        raise SystemExit('还没有数据库，无需备份。')
    target_dir = ROOT / 'backups'
    target_dir.mkdir(exist_ok=True)
    target = target_dir / ('guanlan-' + datetime.datetime.now().strftime('%Y%m%d-%H%M%S') + '.zip')
    with tempfile.TemporaryDirectory() as tmp:
        snapshot = Path(tmp) / 'guanlan.sqlite3'
        src = sqlite3.connect(config.DB_PATH)
        dst = sqlite3.connect(snapshot)
        with dst:
            src.backup(dst)
        dst.close()
        src.close()
        with zipfile.ZipFile(target, 'w', zipfile.ZIP_DEFLATED) as archive:
            archive.write(snapshot, 'data/guanlan.sqlite3')
            if config.FILES.exists():
                for file in config.FILES.rglob('*'):
                    if file.is_file() and not file.name.startswith('.part-'):
                        archive.write(file, Path('data') / file.relative_to(config.DATA))
            archive.write(ROOT / 'config' / 'sources.json', 'config/sources.json')
    print(target)
    print('提示：备份包含邮箱设置。Windows 上的邮箱授权码已加密，只能在本机本账户下使用。')


if __name__ == '__main__':
    main()
