"""All attempts retained; same eight prompts at concurrency 1 and 2."""
import concurrent.futures
import json
import time
import urllib.request
import urllib.error
from pathlib import Path

def request(path,payload=None):
    req=urllib.request.Request('http://127.0.0.1:8091'+path,data=json.dumps(payload).encode() if payload is not None else None,headers={'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req,timeout=180) as r:return r.status,json.load(r)
    except urllib.error.HTTPError as e:return e.code,json.load(e)

def main():
    root=Path('hw8910/evidence')
    observations=[]
    for _ in range(180):
        try:ready=request('/ready')
        except OSError as exc:ready=(0,{'error':str(exc)})
        observations.append({'time':time.time(),'status':ready[0],'body':ready[1]})
        if ready[0]==200:break
        time.sleep(1)
    else:raise RuntimeError('Model never ready')
    (root/'readiness.json').write_text(json.dumps(observations,indent=2))
    before=request('/debug')[1]
    invalid=request('/generate',{'prompt':'x','max_new_tokens':100000})
    after=request('/debug')[1]
    assert invalid[0]==422 and before['calls']==after['calls']
    (root/'invalid-request.json').write_text(json.dumps({'before':before,'response':invalid,'after':after},indent=2))
    golden=[json.loads(x) for x in Path('data/eval/golden.jsonl').read_text().splitlines()][:8]
    attempts=[];summary=[]
    def one(pair):
        mode,i,row=pair;start=time.perf_counter()
        try:status,body=request('/generate',{'prompt':row['input'],'max_new_tokens':32});error=None if status==200 else str(body)
        except Exception as e:status=0;body={};error=str(e)
        return dict(id=row['id'],mode=mode,status=status,error=error,client_seconds=time.perf_counter()-start,**body)
    for mode in (1,2):
        start=time.perf_counter()
        with concurrent.futures.ThreadPoolExecutor(max_workers=mode) as pool:
            group=list(pool.map(one,[(mode,i,row) for i,row in enumerate(golden)]))
        elapsed=time.perf_counter()-start;attempts+=group
        successful=[x for x in group if x['status']==200];lat=[x['client_seconds'] for x in successful]
        summary.append(dict(concurrency=mode,n=len(group),success=len(successful),errors=len(group)-len(successful),
                            batch_seconds=elapsed,successful_requests_per_second=len(successful)/elapsed,
                            mean_success_latency=sum(lat)/len(lat) if lat else None,max_success_latency=max(lat) if lat else None,
                            error_latencies=[x['client_seconds'] for x in group if x['status']!=200]))
    (root/'requests.jsonl').write_text(''.join(json.dumps(x,ensure_ascii=False)+'\n' for x in attempts))
    (root/'benchmark.json').write_text(json.dumps(summary,indent=2))
    print(json.dumps(summary,indent=2));print('Real answer:',attempts[0]['answer'])

if __name__=='__main__':main()
