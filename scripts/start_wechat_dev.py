"""Interactive local bootstrap: secret stays in process memory, never in Git."""
import getpass
import json
import os
from pathlib import Path
import secrets
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from sqlalchemy import select, update, func
from backend import auth, catalog
from backend.import_legacy import import_snapshot
from backend.settings import Settings
from backend.storage import make_engine, migrate, tables as t


def configure_local_debug():
    # This launcher binds only 127.0.0.1. Keep the checked-in project defaults
    # strict and override only this computer's ignored developer-tools config.
    path = ROOT / 'miniprogram' / 'project.private.config.json'
    config = json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else {}
    config.setdefault('setting', {})['urlCheck'] = False
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def main():
    configure_local_debug()
    folder = ROOT / 'data-v2' / 'wechat-dev'
    folder.mkdir(parents=True, exist_ok=True)
    config = json.loads((ROOT / 'config' / 'wechat.json').read_text(encoding='utf-8'))
    print('AppID: ' + config['appid'])
    print('请输入对应小程序的 AppSecret（输入隐藏；只保留在当前进程，不写入文件）。')
    secret = getpass.getpass('AppSecret: ').strip()
    if not secret:
        raise SystemExit('未输入密钥，本次没有启动登录联调。')
    os.environ.update(OBS_DATABASE_URL='sqlite:///' + str(folder / 'observatory.sqlite3'),
                      OBS_WECHAT_APPID=config['appid'], OBS_WECHAT_APP_SECRET=secret,
                      OBS_ADMIN_TOKEN=secrets.token_urlsafe(32), OBS_FILES_ROOT=str(folder))
    engine = make_engine(Settings.load().database_url)
    migrate(engine)
    with engine.connect() as conn:
        empty = not conn.scalar(select(func.count()).select_from(t['sources']))
    if empty:
        legacy = ROOT / 'data' / 'observatory.sqlite3'
        if legacy.is_file():
            import_snapshot(engine, legacy, apply=True, target_files=folder)
        else:
            with engine.begin() as conn:
                catalog.seed(conn)
    with engine.begin() as conn:
        bound = conn.scalar(select(func.count()).select_from(t['wechat_identities']).where(
            t['wechat_identities'].c.appid == config['appid']))
        if not bound:
            owner = conn.scalar(select(t['users'].c.id).where(t['users'].c.id == 'legacy-owner'))
            conn.execute(update(t['invitations']).where(t['invitations'].c.used_at.is_(None),
                         t['invitations'].c.role == 'admin').values(revoked=1))
            invitation = auth.issue_invitation(conn, 'admin', target_user=owner)
            print('首次绑定的一次性管理员邀请码（请只粘贴到你的小程序）：\n' + invitation)
    print('本机接口：http://127.0.0.1:8842；此终端关闭后联调服务停止。')
    print('本机开发者工具与手机网络环境不同；真机需要可达的 HTTPS 服务地址。')
    engine.dispose()
    import uvicorn
    try:
        uvicorn.run('backend.api:create_app', factory=True, host='127.0.0.1', port=8842, access_log=False)
    finally:
        os.environ.pop('OBS_WECHAT_APP_SECRET', None)


if __name__ == '__main__':
    main()
