"""Live official article -> isolated upstream -> V2 versions -> protected detail API."""
import json
import os
from pathlib import Path
import secrets
import socket
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import select, func
from backend import catalog, queue, worker
from backend.api import create_app
from backend.engine_client import EngineClient
from backend.settings import Settings
from backend.storage import make_engine, migrate, tables as t
from fastapi.testclient import TestClient


def main():
    python = ROOT / '.venv' / 'Scripts' / 'python.exe' if os.name == 'nt' else Path(sys.executable)
    folder_root = ROOT / 'data-v2'
    folder_root.mkdir(exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix='live-monitor-', dir=folder_root))
    engine = make_engine('sqlite:///' + str(folder / 'observatory.sqlite3'))
    migrate(engine)
    with engine.begin() as conn:
        catalog.seed(conn)
        aid, _ = catalog.save_article(conn, 'cn-policy-laws', dict(
            url='https://exportcontrol.mofcom.gov.cn/article/zcfg/gnzcfg/flfg/202111/226.html',
            title='官方文章 · 226'), True)
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        port = sock.getsockname()[1]
    settings = Settings('sqlite://', secrets.token_urlsafe(32), f'http://127.0.0.1:{port}',
                        secrets.token_urlsafe(32), folder)
    env = os.environ.copy()
    env.update(OBS_ENGINE_DATA=str(folder / 'engine'), OBS_ENGINE_PORT=str(port),
               OBS_ENGINE_KEY=settings.engine_key, PYTHONIOENCODING='utf-8',
               FETCH_WORKERS='1', LOGGER_LEVEL='WARNING', LITELLM_LOCAL_MODEL_COST_MAP='True')
    with (folder / 'engine.log').open('w', encoding='utf-8') as log:
        process = subprocess.Popen([str(python), '-X', 'utf8', '-m', 'backend.engine_bootstrap'],
            cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        try:
            client = EngineClient(settings)
            deadline = time.monotonic() + 60
            while True:
                try:
                    client.api('systeminfo')
                    break
                except Exception:
                    if process.poll() is not None or time.monotonic() > deadline:
                        raise RuntimeError('Isolated engine did not start; inspect its local log') from None
                    time.sleep(1)

            def run(kind):
                with engine.begin() as conn:
                    queue.enqueue(conn, uuid.uuid4().hex, kind, {'article_id': aid}, resource='article:' + aid)
                worker.run_once(engine, settings, client)

            run('inspect_article')
            run('sync_article')
            deadline = time.monotonic() + 90
            while True:
                with engine.connect() as conn:
                    count = conn.scalar(select(func.count()).select_from(t['versions']))
                if count:
                    break
                if time.monotonic() > deadline:
                    raise RuntimeError('No validated body snapshot within the live verification window')
                time.sleep(3)
                run('sync_article')
            with TestClient(create_app(settings, engine)) as api:
                response = api.get('/api/v1/articles/' + aid,
                                   headers={'Authorization': 'Bearer ' + settings.admin_token})
                response.raise_for_status()
                detail = response.json()
                assert detail['title'] == '中华人民共和国出口管制法'
                assert len(detail['versions'][0]['content']) > 100
                print(json.dumps({'verified': True, 'title': detail['title'],
                    'versions': len(detail['versions']), 'content_chars': len(detail['versions'][0]['content']),
                    'evidence_directory': str(folder)}, ensure_ascii=False, indent=2))
        finally:
            process.terminate()
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)
            engine.dispose()


if __name__ == '__main__':
    main()
