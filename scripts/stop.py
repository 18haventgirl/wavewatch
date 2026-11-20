"""Stop only the two verified processes recorded by this project."""
import json
import os
from pathlib import Path
import psutil

root=Path(__file__).resolve().parents[1]
runtime=root/'data'/'runtime.json'
if not runtime.exists():
    raise SystemExit('没有找到本项目的运行记录。')
state=json.loads(runtime.read_text(encoding='utf-8'))
for key,script in [('engine_pid','engine_runner.py'),('app_pid','run.py')]:
    try:
        proc=psutil.Process(state[key])
        command=proc.cmdline()
        if Path(proc.cwd()).resolve()!=root or not any(Path(arg).name==script for arg in command[1:]):
            raise SystemExit('进程身份校验不符，未执行停止。')
        proc.terminate()
        proc.wait(timeout=15)
    except psutil.NoSuchProcess:
        pass
runtime.unlink(missing_ok=True)
print('观澜监测服务已停止。')
