"""Portable submission: eval data/reports/logs, explicitly no model or training tensors."""
import hashlib
import json
import zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]


def main():
    files=[]
    for folder,pattern in [('metrics','*.json'),('data/eval','*.jsonl'),('evaluation','*.json')]:
        files.extend(sorted((ROOT/folder).glob(pattern)))
    files += [ROOT/'docs'/name for name in ('conclusion.md','defects.md','comparison.csv','sweep-curves.png','golden-review.md','evaluation-plan.md','eval-lineage.json')]
    files += [ROOT/name for name in ('data.dvc','README.md','params.yaml','compose.yaml')]
    files += [ROOT/'runs'/name for name in ('check-all.log','check-eval.log','gate.log','negative.log','storage.log','promote.log','runner.log','sweep-status.json','report.log')]
    assert all(p.is_file() for p in files)
    assert all(p.suffix not in ('.pt','.safetensors','.bin') for p in files)
    submission=ROOT/'submission';submission.mkdir(exist_ok=True)
    manifest={str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in files}
    target=submission/'hw67-submission.zip'
    with zipfile.ZipFile(target,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for p in files: z.write(p,p.relative_to(ROOT).as_posix())
        z.writestr('SHA256-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    print(f'{target} ({target.stat().st_size:,} bytes); {len(files)} source files; no weights/PT')


if __name__=='__main__':main()
