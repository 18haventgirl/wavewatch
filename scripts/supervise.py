"""Keep the monitor running in the background: restart it if it exits unexpectedly.

Started by ``start.ps1 -Background`` and by the login shortcut that
``autostart.ps1`` creates.  ``stop.ps1`` stops the supervisor first, then the service.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.getenv('WAVEWATCH_DATA') or os.getenv('GUANLAN_DATA') or ROOT / 'data')
LOGS = Path(os.getenv('WAVEWATCH_LOGS') or os.getenv('GUANLAN_LOGS') or ROOT / 'logs')
STATE = DATA / 'supervisor.json'


def python_for_service() -> str:
    # pythonw.exe has no console window; the service itself does not need one.
    exe = Path(sys.executable)
    windowless = exe.with_name('pythonw.exe')
    return str(windowless if windowless.exists() else exe)


def main() -> None:
    DATA.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps({'pid': os.getpid(), 'started': time.time()}), encoding='utf-8')
    failures = 0
    log = open(LOGS / 'supervisor.log', 'a', encoding='utf-8')
    try:
        while True:
            started = time.time()
            log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} starting service\n')
            log.flush()
            flags = 0x08000000 if os.name == 'nt' else 0  # CREATE_NO_WINDOW
            code = subprocess.call([python_for_service(), '-X', 'utf8', str(ROOT / 'run.py'), '--quiet'],
                                   cwd=ROOT, creationflags=flags)
            log.write(f'{time.strftime("%Y-%m-%d %H:%M:%S")} service exited with code {code}\n')
            log.flush()
            if not STATE.exists():
                break                       # stop.ps1 removed the state file: intentional stop
            if code == 1 and time.time() - started < 5:
                # Usually "port already in use": another copy is running.  Do not spin.
                failures += 1
            else:
                failures = 0 if time.time() - started > 600 else failures + 1
            time.sleep(min(300, 5 * 2 ** min(failures, 6)))
    finally:
        log.close()
        STATE.unlink(missing_ok=True)


if __name__ == '__main__':
    main()
