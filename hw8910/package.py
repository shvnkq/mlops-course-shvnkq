"""Evidence bundle excludes model weights, virtualenv, caches and volumes."""
import hashlib
import json
import zipfile
from pathlib import Path

def main():
    root=Path('hw8910');files=[p for p in (root/'evidence').iterdir() if p.is_file() and p.suffix in ('.json','.jsonl','.log')]
    files+=[root/'REPORT.md',root/'defects.csv',Path('README.md'),Path('SOURCE.md'),Path('pyproject.toml'),Path('uv.lock')]
    files+=list(Path('metrics').glob('*-eval.json'))+list(Path('metrics').glob('*-outputs.json'))
    files+=list(Path('data/eval').glob('*.jsonl'))
    out=Path('submission');out.mkdir(exist_ok=True)
    with zipfile.ZipFile(out/'hw8910-submission.zip','w',zipfile.ZIP_DEFLATED) as z:
        for p in files:
            assert p.suffix not in ('.pt','.safetensors','.bin')
            z.write(p,p.as_posix())
        z.writestr('SHA256-MANIFEST.json',json.dumps({str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in files},indent=2))
    print(out/'hw8910-submission.zip',len(files),'files; no weights/PT')
if __name__=='__main__':main()
