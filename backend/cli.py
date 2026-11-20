import argparse
import json
import logging
from backend.settings import Settings
from backend.storage import make_engine, migrate


def main():
    parser = argparse.ArgumentParser(description='观澜服务器版开发工具')
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('migrate')
    commands.add_parser('seed')
    commands.add_parser('scheduler')
    commands.add_parser('tick')
    worker = commands.add_parser('worker')
    worker.add_argument('--once', action='store_true')
    legacy = commands.add_parser('import-legacy')
    legacy.add_argument('path')
    legacy.add_argument('--apply', action='store_true')
    legacy.add_argument('--owner', default='legacy-owner')
    legacy.add_argument('--target-files')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    engine = make_engine(Settings.load().database_url)
    try:
        if args.command == 'migrate':
            migrate(engine)
            print('Database migrated')
        elif args.command == 'seed':
            from backend.catalog import seed
            with engine.begin() as conn:
                seed(conn)
            print('Five China sources configured')
        elif args.command == 'import-legacy':
            from backend.import_legacy import import_snapshot
            print(json.dumps(import_snapshot(engine, args.path, args.owner, args.apply, args.target_files), ensure_ascii=False, indent=2))
        elif args.command in ('scheduler', 'tick'):
            from backend.scheduler import tick, tick_monitoring, serve
            print({'sources': tick(engine), 'monitoring': tick_monitoring(engine)}) if args.command == 'tick' else serve(engine)
        elif args.command == 'worker':
            from backend.worker import run_once, serve
            print(run_once(engine)) if args.once else serve(engine)
    finally:
        engine.dispose()


if __name__ == '__main__':
    main()
