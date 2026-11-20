from __future__ import annotations
import atexit
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT=Path(__file__).resolve().parent


def free_port(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1',port))
        except OSError:
            raise SystemExit(f'端口 {port} 已在使用中。请先停止现有实例。')


def main():
    for port in (8840,8841):
        free_port(port)
    from app import db,engine
    db.init()
    engine.prepare_local_scope()
    data=ROOT/'data'
    logs=ROOT/'logs'
    logs.mkdir(exist_ok=True)
    (data/'engine').mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.update(PYTHONIOENCODING='utf-8',LOGGER_LEVEL='WARNING',FETCH_WORKERS='3',LITELLM_LOCAL_MODEL_COST_MAP='True')
    args=[sys.executable,str(ROOT/'engine_runner.py'),'-h','127.0.0.1','-p','8841','-d',str(data/'engine'),'-C']
    if not any((data/'engine'/name).exists() for name in ('changedetection.json','url-watches.json')):
        args+=['-u','https://exportcontrol.mofcom.gov.cn/articleList.shtml?columnID=13&num=1','-u0',json.dumps({'title':'中国出口管制信息网 · 法律入口','paused':True})]
    engine_log=open(logs/'engine.log','a',encoding='utf-8')
    child=subprocess.Popen(args,cwd=ROOT,env=env,stdout=engine_log,stderr=subprocess.STDOUT)
    runtime=data/'runtime.json'
    runtime.write_text(json.dumps({'app_pid':os.getpid(),'engine_pid':child.pid,'python':sys.executable}),encoding='utf-8')
    def cleanup():
        if child.poll() is None:
            child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
        engine_log.close()
        runtime.unlink(missing_ok=True)
    atexit.register(cleanup)
    print('Local: http://127.0.0.1:8840',flush=True)
    import uvicorn
    try:
        uvicorn.run('app.main:app',host='127.0.0.1',port=8840,log_level='warning',ws='none')
    finally:
        cleanup()


if __name__=='__main__':
    main()
