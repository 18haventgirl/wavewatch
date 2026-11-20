"""Create a stopped-service backup; do not copy a live SQLite/WAL bundle."""
import datetime
import json
from pathlib import Path
import sys
import zipfile
import psutil

root=Path(__file__).resolve().parents[1]
runtime=root/'data'/'runtime.json'
if runtime.exists():
    state=json.loads(runtime.read_text(encoding='utf-8'))
    if any(psutil.pid_exists(state.get(key,-1)) for key in ('app_pid','engine_pid')):
        raise SystemExit('请先运行 stop.ps1 停止监测，再执行备份。')
folder=root/'backups'
folder.mkdir(exist_ok=True)
target=folder/('observatory-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S')+'.zip')
with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
    for file in (root/'data').rglob('*'):
        if file.is_file() and file.name!='runtime.json':
            archive.write(file,file.relative_to(root))
    archive.write(root/'config'/'sources.json','config/sources.json')
print(target)
