"""Actual subprocess fault/recovery and preparation invalidation records."""
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

def main():
    evidence=Path('hw8910/evidence');records=[]
    def run(name,args):
        p=subprocess.run([sys.executable,'hw8910/flow.py',*args],env=dict(os.environ,PREFECT_SERVER_ANALYTICS_ENABLED='false'),capture_output=True,text=True)
        (evidence/(name+'.log')).write_text(p.stdout+p.stderr)
        records.append({'experiment':name,'args':args,'exit_code':p.returncode,'cached':'Cached(' in p.stderr,'prepared':'PREPARED' in p.stdout})
        return p
    assert run('flow-repeat',[]).returncode==0
    assert len(Path('hw8910/state/publications.jsonl').read_text().splitlines())==1
    probe=Path('hw8910/state/preparation-probe.jsonl');probe.write_bytes(Path('data/eval/golden.jsonl').read_bytes())
    assert run('flow-probe-initial',['--data',str(probe)]).returncode==0
    content=probe.read_text().splitlines();row=json.loads(content[0]);row['input']+=' Проверка подготовки.';content[0]=json.dumps(row,ensure_ascii=False);probe.write_text('\n'.join(content)+'\n')
    p=run('flow-input-changed',['--data',str(probe)]);assert p.returncode==0 and 'PREPARED' in p.stdout
    recovery=Path('hw8910/state-recovery');shutil.copytree('hw8910/state',recovery,ignore=shutil.ignore_patterns('publications.jsonl'),dirs_exist_ok=False)
    p=run('flow-pointer-crash',['--root',str(recovery),'--fail-after-pointer']);assert p.returncode!=0
    assert not (recovery/'publications.jsonl').exists()
    for name in ['flow-pointer-repair','flow-pointer-repeat']:
        assert run(name,['--root',str(recovery)]).returncode==0
    assert len((recovery/'publications.jsonl').read_text().splitlines())==1
    # Real release refusal leaves the actual accepted pointer byte-identical.
    import release
    target=Path('hw8910/state/accepted.json');before=target.read_bytes()
    manifest=json.loads(target.read_text());report=json.loads(Path('hw8910/state/release-report.json').read_text())
    refused=[]
    for kind in ['incomplete','wrong-model','reject','nan']:
        r=json.loads(json.dumps(report))
        if kind=='incomplete':r.pop('metrics')
        elif kind=='wrong-model':r['model_id']='other'
        elif kind=='reject':r['passed']=False
        else:r['metrics']['accuracy']=float('nan')
        try:release.publish(manifest,r,target)
        except ValueError:pass
        else:raise AssertionError('Unsafe report accepted')
        assert target.read_bytes()==before
        refused.append({'case':kind,'before_sha256':hashlib.sha256(before).hexdigest(),'after_sha256':hashlib.sha256(target.read_bytes()).hexdigest()})
    (evidence/'flow-experiments.json').write_text(json.dumps(records,indent=2))
    (evidence/'refusals.json').write_text(json.dumps(refused,indent=2))
    print(json.dumps(records,indent=2));print('PASS refusals, invalidation, repeat and crash consistency')

if __name__=='__main__':main()
