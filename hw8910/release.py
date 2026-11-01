"""Учебный прототип выпуска. Реализация содержит дефекты; см. CONTRACTS.txt."""
import hashlib
import json
import os
import math
import re
import tempfile
from pathlib import Path


def cache_key(data_path: Path, config: dict) -> str:
    return digest({'data_sha256': hashlib.sha256(Path(data_path).read_bytes()).hexdigest(), 'config': config})


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',',':'),ensure_ascii=False,allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def validate_release(manifest: dict, report: dict) -> None:
    try:
        if type(manifest['schema_version']) is not int or manifest['schema_version'] != 1:
            raise ValueError('schema_version must be integer 1')
        for key in ('model_id','artifact_uri'):
            if not isinstance(manifest[key],str) or not manifest[key].strip(): raise ValueError(key)
        if not isinstance(manifest['runtime'],dict) or not manifest['runtime']: raise ValueError('runtime')
        for key in ('model_sha256','protocol_sha256','golden_sha256','runtime_sha256'):
            if not isinstance(manifest[key],str) or not re.fullmatch('[0-9a-f]{64}',manifest[key]): raise ValueError(key)
            if report[key]!=manifest[key]: raise ValueError('Report mismatch: '+key)
        if digest(manifest['runtime'])!=manifest['runtime_sha256']: raise ValueError('Runtime hash mismatch')
        if report['status']!='complete' or report['passed'] is not True: raise ValueError('Not a complete PASS')
        if report['model_id']!=manifest['model_id']: raise ValueError('Wrong model')
        if not isinstance(report['evaluation_run_id'],str) or not report['evaluation_run_id'].strip(): raise ValueError('Missing eval')
        for name in ('accuracy','format_rate'):
            v=report['metrics'][name]
            if type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=1: raise ValueError('Invalid '+name)
    except (KeyError,TypeError,AttributeError) as exc:
        raise ValueError('Incomplete release contract') from exc


def publish(manifest: dict, report: dict, target: Path) -> None:
    validate_release(manifest, report)
    target.parent.mkdir(parents=True, exist_ok=True)
    payload=canonical(manifest)+b'\n'
    if target.exists() and target.read_bytes()==payload: return
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(dir=target.parent,suffix='.tmp',delete=False) as f:
            tmp=f.name;f.write(payload);f.flush();os.fsync(f.fileno())
        os.replace(tmp,target)
    finally:
        if tmp and Path(tmp).exists(): Path(tmp).unlink()


def verify_files(manifest, root):
    hashes={}
    for name, expected in manifest['file_hashes'].items():
        p=(Path(root)/name).resolve()
        if not p.is_relative_to(Path(root).resolve()): raise ValueError('Unsafe artifact path')
        hashes[name]=hashlib.sha256(p.read_bytes()).hexdigest()
        if hashes[name]!=expected: raise ValueError('Artifact changed: '+name)
    if not hashes or digest(hashes)!=manifest['model_sha256']: raise ValueError('Model files hash mismatch')
