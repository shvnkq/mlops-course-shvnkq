"""One-writer durable Prefect release: existing training result, never retraining."""
import argparse
import hashlib
import json
import os
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from prefect import flow, task
import release


def key(context, parameters):return release.cache_key(Path(parameters['data_path']),parameters['config'])


@task(cache_key_fn=key,persist_result=True)
def preparation(data_path,config):
    data=Path(data_path).read_bytes()
    rows=[json.loads(line) for line in data.decode().splitlines() if line.strip()]
    if not rows or any(not isinstance(r.get('input'),str) for r in rows):raise ValueError('Bad preparation input')
    print('PREPARED',hashlib.sha256(data).hexdigest(),flush=True)
    return {'rows':len(rows),'input_sha256':hashlib.sha256(data).hexdigest()}


@task(persist_result=False,retries=0)
def artifact(root):
    manifest=json.loads((Path(root)/'manifest.json').read_text())
    release.verify_files(manifest,root)
    return manifest


@task(persist_result=False,retries=0)
def admission(root,manifest):
    # Recompute HW67 metrics from original raw answers, verify protocol and run.
    from evaluation.cli import current_reports
    from evaluation.solution import quality_gate
    a,b=current_reports()
    config=json.loads(Path('evaluation/params.json').read_text())
    result=quality_gate(a,b,config['critical_slices'])
    if b['model']['run_id']!=manifest['training_run_id']:raise ValueError('Wrong training run')
    report={k:manifest[k] for k in ('model_id','model_sha256','protocol_sha256','golden_sha256','runtime_sha256')}
    source={}
    for name in ('baseline-eval','candidate-eval','baseline-outputs','candidate-outputs'):
        p=Path('metrics')/(name+'.json');source[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest()
    if source!=manifest['evaluation_sources']:raise ValueError('Evaluation files changed')
    report.update(status='complete',passed=result['passed'],evaluation_run_id=b['evaluation_run_id'],metrics=b['overall'],sources=source)
    release.validate_release(manifest,report)
    (Path(root)/'release-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report


@task(persist_result=False,retries=0)
def publication(root,manifest,report,fail_pointer=False):
    root=Path(root);release.verify_files(manifest,root)
    release.publish(manifest,report,root/'accepted.json')
    if fail_pointer:raise RuntimeError('Injected fault after pointer, before journal')
    ident=release.digest({'manifest':manifest,'report':report})
    p=root/'publications.jsonl'
    existing=[json.loads(x) for x in p.read_text().splitlines()] if p.exists() else []
    if not any(x['release_id']==ident for x in existing):
        with p.open('a') as f:
            f.write(json.dumps({'release_id':ident,'model_id':manifest['model_id']})+'\n');f.flush();os.fsync(f.fileno())
    print('PUBLISHED',ident,flush=True)
    return ident


@flow(name='hw8910-release',persist_result=False)
def release_flow(root='hw8910/state',data='data/eval/golden.jsonl',fail=False,fail_pointer=False):
    root=Path(root)
    manifest=json.loads((root/'manifest.json').read_text())
    runtime=manifest['runtime']
    config={'tokenizer_revision':runtime['tokenizer_sha256'],'template_sha256':runtime['template_sha256'],
            'max_length':4096,'code_revision':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    prep=preparation(data,config)
    if fail:raise RuntimeError('Injected fault after preparation')
    m=artifact(str(root));report=admission(str(root),m)
    return publication(str(root),m,report,fail_pointer)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',default='hw8910/state');p.add_argument('--data',default='data/eval/golden.jsonl')
    p.add_argument('--fail-after-prepare',action='store_true');p.add_argument('--fail-after-pointer',action='store_true');a=p.parse_args()
    release_flow(a.root,a.data,a.fail_after_prepare,a.fail_after_pointer)
