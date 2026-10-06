"""Run the unchanged course checker in Git Bash, with UTF-8 on Windows."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--script", default="tests/check.sh")
    args = ap.parse_args()
    script = (ROOT / args.script).resolve()
    if not script.is_relative_to(ROOT / "tests") or not script.is_file():
        raise SystemExit("Checker must be a file inside tests/")
    if os.name == "nt":
        git_exec = subprocess.check_output(["git", "--exec-path"], text=True).strip()
        bash = str((Path(git_exec) / "../../../bin/bash.exe").resolve())
    else:
        bash = shutil.which("bash")
    if not bash or not Path(bash).is_file():
        raise SystemExit("Install Git Bash to run the course checker")
    env = dict(os.environ, PYTHONUTF8="1", PYTHONIOENCODING="utf-8", PYTHONHASHSEED="42")
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    runs = ROOT / "runs"
    runs.mkdir(exist_ok=True)
    status = {"started_at": datetime.now().astimezone().isoformat(), "script": args.script,
              "checker_sha256": hashlib.sha256(script.read_bytes()).hexdigest(), "state": "running"}
    log = runs / ("check-hw3.log" if "hw3" in script.name else "check.log")
    proc = subprocess.Popen([bash, args.script], cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    with log.open("w", encoding="utf-8", buffering=1) as stream:
        for line in proc.stdout:
            print(line, end="", flush=True)
            stream.write(line)
    code = proc.wait()
    status.update(exit_code=code, state="passed" if code == 0 else "failed",
                  finished_at=datetime.now().astimezone().isoformat(), log=str(log))
    log.with_suffix(".status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2), encoding="utf-8")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
