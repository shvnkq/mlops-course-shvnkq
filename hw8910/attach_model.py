"""Retrieve accepted HW67 artifact and bind its original full evaluation, no sweep."""
import hashlib
import json
import shutil
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import release

def main():
    from evaluation.cli import candidate_model,manifest_for,current_reports
    from evaluation.solution import quality_gate
    spec=candidate_model();meta,adapter=manifest_for(spec);a,b=current_reports()
    cfg=json.loads(Path('evaluation/params.json').read_text());quality_gate(a,b,cfg['critical_slices'])
    root=Path('hw8910/state');root.mkdir(exist_ok=True)
    dest=root/'adapter';shutil.copytree(adapter,dest,dirs_exist_ok=True)
    hashes={'adapter/'+p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(dest.iterdir()) if p.is_file()}
    runtime={'base_name':meta['model']['name'],'base_revision':meta['model']['revision'],
             'tokenizer_sha256':release.digest({k:v for k,v in hashes.items() if 'token' in k or 'vocab' in k or 'merges' in k}),
             'template_sha256':hashes['adapter/chat_template.jinja'],
             'generation':{'system':cfg['system'],'max_new_tokens':cfg['max_new_tokens'],'do_sample':False,
                           'seed':cfg['seed'],'enable_thinking':cfg['enable_thinking']},
             'dtype':meta['model']['dtype'],'device':'mps','torch':'2.14.0','transformers':'5.17.0','peft':'0.21.0'}
    sources={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in [Path('metrics')/(s+'.json') for s in ('baseline-eval','candidate-eval','baseline-outputs','candidate-outputs')]}
    manifest={'schema_version':1,'model_id':spec['run_id'],'training_run_id':spec['run_id'],'artifact_uri':spec['uri'],
              'model_sha256':release.digest(hashes),'file_hashes':hashes,'runtime':runtime,'runtime_sha256':release.digest(runtime),
              'protocol_sha256':b['protocol_sha256'],'golden_sha256':b['golden_sha256'],'evaluation_sources':sources,
              'provenance_note':'Existing accepted HW67 training result; no new training or generation protocol change'}
    (root/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2))
    print('Retrieved real accepted adapter',spec['run_id'],'and bound original full evaluation',b['evaluation_run_id'])

if __name__=='__main__':main()
