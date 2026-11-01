"""FastAPI with the shared validated ServiceState and actual Transformers/PEFT backend."""
import argparse
import json
import sys
from pathlib import Path
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
import uvicorn
from service import ServiceState,StubBackend

class ModelBackend:
    def __init__(self,manifest,root):
        import torch
        import transformers,peft
        from transformers import AutoTokenizer,AutoModelForCausalLM
        from peft import PeftModel
        self.loaded_id=manifest['model_id'];self.runtime_sha256=manifest['runtime_sha256'];self.calls=0
        r=manifest['runtime'];self.runtime=r;g=r['generation']
        if (torch.__version__.split('+')[0],transformers.__version__,peft.__version__)!=(r['torch'],r['transformers'],r['peft']):raise ValueError('Runtime libraries changed: reevaluate')
        torch.manual_seed(g['seed']);torch.set_num_threads(4)
        adapter=Path(root)/'adapter'
        self.tok=AutoTokenizer.from_pretrained(adapter,local_files_only=True)
        model=AutoModelForCausalLM.from_pretrained(r['base_name'],revision=r['base_revision'],dtype=getattr(torch,r['dtype']),local_files_only=True)
        self.model=PeftModel.from_pretrained(model,adapter).to(r['device']).eval()
    def generate(self,prompt,limit):
        import torch
        self.calls+=1;r=self.runtime;g=r['generation']
        text=self.tok.apply_chat_template([{'role':'system','content':g['system']},{'role':'user','content':prompt}],tokenize=False,add_generation_prompt=True,enable_thinking=g['enable_thinking'])
        batch=self.tok(text,return_tensors='pt').to(r['device'])
        with torch.inference_mode():
            out=self.model.generate(**batch,max_new_tokens=limit,do_sample=False,pad_token_id=self.tok.pad_token_id or self.tok.eos_token_id)
        result=out[0,batch['input_ids'].shape[1]:]
        return {'answer':self.tok.decode(result,skip_special_tokens=True),'output_tokens':len(result)}

def create_app(root,warmup=0,stub=False):
    state=ServiceState(Path(root),warmup,StubBackend if stub else lambda manifest:ModelBackend(manifest,root))
    app=FastAPI()
    @app.get('/health')
    def health():return {'alive':True,'backend':'STUB ONLY' if stub else 'Transformers + PEFT'}
    @app.get('/ready')
    def ready():return JSONResponse({'ready':state.ready,'error':state.error},status_code=200 if state.ready else 503)
    @app.get('/debug')
    def debug():return {'calls':state.backend.calls if state.backend else 0,'warmup_finished':state.warmup_finished.is_set(),'loaded_id':state.backend.loaded_id if state.backend else None}
    @app.post('/generate')
    async def generate(request:Request):
        if len(await request.body())>65536:return JSONResponse({'error':'body too large'},status_code=413)
        try:
            payload=await request.json()
            from starlette.concurrency import run_in_threadpool
            return await run_in_threadpool(state.generate,payload)
        except (ValueError,TypeError,KeyError):return JSONResponse({'error':'invalid request'},status_code=422)
        except RuntimeError:return JSONResponse({'error':'not ready'},status_code=503)
    return app

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--workspace',default='hw8910/state');p.add_argument('--port',type=int,default=8091);p.add_argument('--warmup-seconds',type=float,default=0);p.add_argument('--stub',action='store_true');a=p.parse_args()
    uvicorn.run(create_app(a.workspace,a.warmup_seconds,a.stub),host='127.0.0.1',port=a.port)
