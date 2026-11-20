"""Run server tests against an owned disposable official PostgreSQL container."""
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
import uuid
import argparse
import tempfile
from urllib.parse import quote
import psycopg

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--legacy-source', help='Additionally rehearse a read-only import of a real SQLite v5 database')
    args = parser.parse_args()
    name = 'guanlan-v2-test-' + uuid.uuid4().hex[:12]
    password = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env['POSTGRES_PASSWORD'] = password
    try:
        subprocess.run(['docker', 'run', '-d', '--rm', '--name', name,
                        '-e', 'POSTGRES_PASSWORD', '-e', 'POSTGRES_DB=guanlan_v2_test',
                        '-p', '127.0.0.1::5432', 'postgres:17-alpine'], env=env, check=True, timeout=240)
        port = subprocess.check_output(['docker', 'port', name, '5432/tcp'], text=True).strip().rsplit(':', 1)[1]
        plain = f'postgresql://postgres:{quote(password)}@127.0.0.1:{port}/guanlan_v2_test'
        deadline = time.monotonic() + 60
        while True:
            try:
                with psycopg.connect(plain, connect_timeout=2):
                    break
            except psycopg.OperationalError:
                if time.monotonic() > deadline:
                    raise RuntimeError('Test PostgreSQL did not become ready') from None
                time.sleep(1)
        env['OBS_TEST_DATABASE_URL'] = plain.replace('postgresql://', 'postgresql+psycopg://', 1)
        result = subprocess.run([sys.executable, '-m', 'unittest', 'discover', '-s', 'backend/tests', '-v'],
                                cwd=ROOT, env=env, timeout=180)
        if result.returncode == 0 and args.legacy_source:
            env['OBS_DATABASE_URL'] = env['OBS_TEST_DATABASE_URL']
            subprocess.run([sys.executable, '-m', 'backend.cli', 'migrate'], cwd=ROOT, env=env, check=True)
            with tempfile.TemporaryDirectory(prefix='guanlan-import-') as files:
                subprocess.run([sys.executable, '-X', 'utf8', '-m', 'backend.cli', 'import-legacy',
                                str(Path(args.legacy_source).resolve()), '--apply', '--target-files', files],
                               cwd=ROOT, env=env, check=True)
        return result.returncode
    finally:
        # Removes only the container created by this invocation, including its test data.
        subprocess.run(['docker', 'rm', '-f', name], capture_output=True, timeout=30)


if __name__ == '__main__':
    raise SystemExit(main())
