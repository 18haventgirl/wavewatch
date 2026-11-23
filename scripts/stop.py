"""Stop the supervisor (if any) and the service, after verifying they belong to this project."""
from __future__ import annotations

import json
from pathlib import Path

import psutil

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'data'


def stop(state_file: Path, script: str) -> bool:
    if not state_file.exists():
        return False
    try:
        pid = json.loads(state_file.read_text(encoding='utf-8'))['pid']
    except (ValueError, KeyError, OSError):
        state_file.unlink(missing_ok=True)
        return False
    state_file.unlink(missing_ok=True)   # tells the supervisor this stop is intentional
    try:
        proc = psutil.Process(pid)
        if not any(Path(arg).name == script for arg in proc.cmdline()[1:]):
            print(f'进程 {pid} 不是 Tidegaze THVS 的 {script}，未停止。')
            return False
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except psutil.TimeoutExpired:
            proc.kill()
        return True
    except psutil.NoSuchProcess:
        return False


if __name__ == '__main__':
    stopped_supervisor = stop(DATA / 'supervisor.json', 'supervise.py')
    stopped_service = stop(DATA / 'runtime.json', 'run.py')
    if stopped_supervisor or stopped_service:
        print('Tidegaze THVS 已停止。')
    else:
        print('没有发现正在运行的 Tidegaze THVS。')
