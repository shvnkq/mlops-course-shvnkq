"""Detached sweep runner with persistent progress; never changes configs or thresholds."""
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    os.chdir(ROOT)
    sys.stdout.reconfigure(line_buffering=True)
    runs = ROOT/'runs'
    runs.mkdir(exist_ok=True)
    status = {'state':'running','pid':os.getpid(),'started_at':datetime.now().astimezone().isoformat()}
    target = runs/'sweep-status.json'
    def save():
        tmp=target.with_suffix('.tmp')
        tmp.write_text(json.dumps(status,ensure_ascii=False,indent=2)+'\n')
        tmp.replace(target)
    save()
    env = dict(os.environ, PYTHONUNBUFFERED='1', PYTHONHASHSEED='42', HF_HUB_OFFLINE='1', TOKENIZERS_PARALLELISM='false')
    awake = subprocess.Popen(['/usr/bin/caffeinate','-i','-w',str(os.getpid())])
    try:
        with (runs/'sweep.log').open('a',encoding='utf-8',buffering=1) as log:
            command=[sys.executable,'-u','-m','src.sweep']
            proc = subprocess.Popen(command,cwd=ROOT,env=env,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,
                                    text=True,encoding='utf-8',bufsize=1)
            status['child_pid']=proc.pid
            save()
            for line in proc.stdout:
                print(line,end='',flush=True)
                log.write(line)
            if proc.wait():
                raise RuntimeError(f'sweep exit code {proc.returncode}')
        status.update(state='completed',finished_at=datetime.now().astimezone().isoformat())
        save()
        print('\nПОИСК ЗАВЕРШЁН: все шесть конфигураций готовы.\nДалее: report, candidate, baseline-init, evaluate и проверки.',flush=True)
    except Exception as exc:
        status.update(state='failed',error=str(exc),finished_at=datetime.now().astimezone().isoformat())
        save()
        raise
    finally:
        awake.terminate()


if __name__=='__main__':
    main()
