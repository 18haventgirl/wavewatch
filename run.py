"""Start the monitor: one process serving the UI/API and running the background workers.

    python run.py            # foreground, logs to console and logs/wavewatch.log
    python run.py --quiet    # no console output (used by the background launcher)
"""
from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from app import config  # noqa: E402


def setup_logging(quiet: bool) -> None:
    config.LOGS.mkdir(parents=True, exist_ok=True)
    handlers: list[logging.Handler] = [logging.handlers.RotatingFileHandler(
        config.LOGS / 'wavewatch.log', maxBytes=2 * 1024 * 1024, backupCount=5, encoding='utf-8')]
    if not quiet:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format='%(asctime)s %(levelname)s %(name)s: %(message)s')
    logging.getLogger('httpx').setLevel(logging.WARNING)


def ensure_port_free() -> None:
    with socket.socket() as sock:
        try:
            sock.bind((config.HOST, config.PORT))
        except OSError:
            raise SystemExit(f'端口 {config.PORT} 已被占用：Wavewatch THVS 可能已经在运行。打开 {config.LOCAL_URL} 查看，或先运行 stop.ps1。')


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--quiet', action='store_true')
    args = parser.parse_args()
    if args.quiet and sys.stdout is None:  # pythonw has no console
        sys.stdout = sys.stderr = open(os.devnull, 'w', encoding='utf-8')
    ensure_port_free()
    setup_logging(args.quiet)
    runtime = config.DATA / 'runtime.json'
    config.DATA.mkdir(parents=True, exist_ok=True)
    runtime.write_text(json.dumps({'pid': os.getpid(), 'python': sys.executable, 'url': config.LOCAL_URL}), encoding='utf-8')
    logging.getLogger('wavewatch').info('starting on %s', config.LOCAL_URL)
    if not args.quiet:
        print(f'{config.APP_NAME} 已启动：{config.LOCAL_URL}  （按 Ctrl+C 停止）', flush=True)
    import uvicorn
    try:
        uvicorn.run('app.main:app', host=config.HOST, port=config.PORT, log_level='warning', ws='none',
                    access_log=False, log_config=None)
    finally:
        runtime.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
