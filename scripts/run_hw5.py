"""Detached, visible sequential training with a durable journal and status."""

import ctypes
import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
RUNS.mkdir(exist_ok=True)
STATUS = RUNS / "status.json"
JOURNAL = RUNS / "training.log"


def main():
    os.chdir(ROOT)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    os.environ.update(PYTHONUNBUFFERED="1", PYTHONIOENCODING="utf-8", PYTHONHASHSEED="42",
                      HF_HUB_OFFLINE="1", TOKENIZERS_PARALLELISM="false")
    if os.name == "nt":
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000001)
    started = datetime.now().astimezone().isoformat()
    state = {"state": "running", "started_at": started, "runner_pid": os.getpid(),
             "active_variant": None, "completed_variants": [], "log": str(JOURNAL)}

    def save():
        temporary = STATUS.with_suffix(".tmp")
        temporary.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temporary.replace(STATUS)

    with JOURNAL.open("a", encoding="utf-8", buffering=1) as journal:
        def emit(text):
            print(text, flush=True)
            journal.write(text + "\n")

        try:
            save()
            emit(f"ДЗ5: старт {started}")
            emit("Два варианта по 192 шага: all_layers, затем freeze14.")
            emit("Ожидаемое время: около 6–8 часов. Это окно можно свернуть.")
            emit("Завершение обоих вариантов отмечается строкой: ОБУЧЕНИЕ ЗАВЕРШЕНО.")
            for variant in ("all_layers", "freeze14", "plot"):
                state["active_variant"] = variant
                cmd = [sys.executable, "-u", "-X", "utf8", "-m", "src.plot" if variant == "plot" else "src.train"]
                if variant != "plot":
                    cmd += ["--variant", variant]
                emit("\n" + " ".join(cmd))
                proc = subprocess.Popen(cmd, cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, encoding="utf-8", errors="replace", bufsize=1)
                state["child_pid"] = proc.pid
                save()
                for line in proc.stdout:
                    emit(line.rstrip("\r\n"))
                if proc.wait() != 0:
                    raise RuntimeError(f"{variant}: код завершения {proc.returncode}")
                if variant != "plot":
                    state["completed_variants"].append(variant)
                save()
            state.update(state="completed", active_variant=None, child_pid=None,
                         finished_at=datetime.now().astimezone().isoformat())
            save()
            emit("\n============================================================")
            emit("ОБУЧЕНИЕ ЗАВЕРШЕНО — ОБА ВАРИАНТА ГОТОВЫ")
            emit("all_layers: 192/192; freeze14: 192/192; docs/curves.png создан.")
            emit("Напишите в чат: обучение закончилось — можно выполнять этап 2.")
            emit("============================================================")
        except Exception as exc:
            state.update(state="failed", error=str(exc), finished_at=datetime.now().astimezone().isoformat())
            save()
            emit(f"\nОШИБКА ОБУЧЕНИЯ: {exc}")
            emit(f"Пришлите последние строки журнала: {JOURNAL}")
            raise
        finally:
            if os.name == "nt":
                ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)


if __name__ == "__main__":
    main()
