"""Real subprocess/filesystem/HTTP regressions, also runnable against original code."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
import urllib.error
from pathlib import Path

PROJECT=Path(os.environ.get('HW8910_PROJECT',Path(__file__).resolve().parents[1]))

class Integration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'lab'
        self.run_lab('init')

    def run_lab(self,*args,env=None):
        return subprocess.run([sys.executable,str(PROJECT/'lab.py'),'--workspace',str(self.root),*args],
                              cwd=self.tmp.name,env=env,text=True,capture_output=True)

    def test_process_reject_and_incompatible(self):
        before=(self.root/'accepted.json').read_bytes()
        for report in ['report-incomplete.json','report-A.json','report-reject.json']:
            result=self.run_lab('run','--report',report)
            self.assertNotEqual(result.returncode,0,result.stdout)
            self.assertEqual((self.root/'accepted.json').read_bytes(),before)

    def test_process_recovery_and_changed_input(self):
        self.assertNotEqual(self.run_lab('run','--fail-after-prepare').returncode,0)
        result=self.run_lab('run');self.assertEqual(result.returncode,0,result.stderr)
        self.assertIn('CACHE_HIT',result.stdout)
        (self.root/'input.txt').write_text('Changed content at same path')
        result=self.run_lab('run');self.assertIn('PREPARED',result.stdout)

    def test_process_repeat_has_one_publication(self):
        for _ in range(2):self.assertEqual(self.run_lab('run').returncode,0)
        self.assertEqual(len((self.root/'publications.jsonl').read_text().splitlines()),1)

    def test_pointer_journal_crash_recovery(self):
        first=self.run_lab('run',env=dict(os.environ,HW8910_FAIL_AFTER_POINTER='1'))
        self.assertNotEqual(first.returncode,0)
        self.assertEqual(json.loads((self.root/'accepted.json').read_text())['model_id'],'fixture-B')
        for _ in range(2):self.assertEqual(self.run_lab('run').returncode,0)
        self.assertEqual(len((self.root/'publications.jsonl').read_text().splitlines()),1)

    def start_server(self,warmup=0):
        with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
        entry=os.environ.get('HW8910_HTTP_ENTRY','service.py')
        p=subprocess.Popen([sys.executable,str(PROJECT/entry),*(['--stub'] if entry=='api.py' else []),'--workspace',str(self.root),'--port',str(port),'--warmup-seconds',str(warmup)],
                           stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,cwd=self.tmp.name)
        self.addCleanup(lambda: self.stop(p))
        base=f'http://127.0.0.1:{port}'
        for _ in range(300):
            try:self.request(base,'/health');return p,base
            except (OSError,urllib.error.URLError):time.sleep(.02)
        self.fail('Server did not start')

    @staticmethod
    def stop(p):
        if p.poll() is None:p.terminate();p.wait(timeout=10)

    def request(self,base,path,data=None):
        req=urllib.request.Request(base+path,data=json.dumps(data).encode() if data is not None else None,headers={'Content-Type':'application/json'})
        try:
            with urllib.request.urlopen(req,timeout=10) as r:return r.status,json.load(r)
        except urllib.error.HTTPError as e:return e.code,json.load(e)

    def wait_ready(self,base):
        for _ in range(100):
            if self.request(base,'/ready')[0]==200:return
            time.sleep(.02)
        self.fail('Never ready')

    def test_http_readiness(self):
        p,base=self.start_server(1)
        self.assertEqual(self.request(base,'/health')[0],200)
        self.assertEqual(self.request(base,'/ready')[0],503)
        self.assertEqual(self.request(base,'/generate',{'prompt':'x','max_new_tokens':32})[0],503)
        self.wait_ready(base)

    def test_http_validation_never_calls_backend(self):
        p,base=self.start_server();self.wait_ready(base)
        calls=self.request(base,'/debug')[1]['calls']
        for payload in [{'prompt':''},{'prompt':'x','max_new_tokens':0},{'prompt':'x','max_new_tokens':100000},{'prompt':'x','max_new_tokens':'32'}]:
            self.assertTrue(400<=self.request(base,'/generate',payload)[0]<500)
        self.assertEqual(self.request(base,'/debug')[1]['calls'],calls)

    def test_http_actual_loaded_version_and_rollback(self):
        p,base=self.start_server();self.wait_ready(base)
        self.assertEqual(self.run_lab('run').returncode,0)
        result=self.request(base,'/generate',{'prompt':'x'})[1]
        self.assertIn('fixture-A',result['answer']);self.assertEqual(result['model_id'],'fixture-A')
        self.stop(p);p,base=self.start_server();self.wait_ready(base)
        self.assertEqual(self.request(base,'/generate',{'prompt':'x'})[1]['model_id'],'fixture-B')
        (self.root/'accepted.json').write_bytes((self.root/'manifest-A.json').read_bytes())
        self.stop(p);p,base=self.start_server();self.wait_ready(base)
        self.assertEqual(self.request(base,'/generate',{'prompt':'x'})[1]['model_id'],'fixture-A')

if __name__=='__main__':unittest.main(verbosity=2)
