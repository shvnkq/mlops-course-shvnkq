"""Reload the same real accepted model in a new API process; no fictitious version B."""
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from measure import request

if __name__=='__main__':
    pid=int(sys.argv[1]);before=request('/generate',{'prompt':'В какой стране находится Beijing? A. China B. Turkey C. Colombia. choices: A, B, C','max_new_tokens':32})
    os.kill(pid,signal.SIGTERM)
    time.sleep(1)
    f=Path('hw8910/evidence/api-restarted.log').open('a')
    p=subprocess.Popen([sys.executable,'-u','hw8910/api.py'],stdout=f,stderr=subprocess.STDOUT,start_new_session=True)
    seen=[]
    for _ in range(90):
        try:state=request('/ready');seen.append(state)
        except OSError:state=(0,{})
        if state[0]==200:break
        time.sleep(1)
    else:raise RuntimeError('Restart not ready')
    after=request('/generate',{'prompt':'В какой стране находится Beijing? A. China B. Turkey C. Colombia. choices: A, B, C','max_new_tokens':32})
    assert before[0]==after[0]==200
    for key in ('model_id','runtime_sha256','answer'):assert before[1][key]==after[1][key]
    Path('hw8910/evidence/restart-smoke.json').write_text(json.dumps({'previous_pid':pid,'current_pid':p.pid,'before':before,'after':after,'readiness':seen},ensure_ascii=False,indent=2))
    print('PASS real model restarted; same loaded model/runtime/answer',p.pid)
