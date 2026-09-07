"""Замер производительности машины на выбранной модели.

Три числа меряются РАЗДЕЛЬНО — смешивать их бессмысленно:
  * время загрузки модели  — разовая стоимость старта;
  * tokens/sec             — скорость генерации, только после прогрева;
  * пиковая RSS            — максимум за процесс, а не снимок в конце.
"""

import json
import statistics
import threading
import time
from pathlib import Path

import psutil
import torch

from src.config import load_params
from src.model import generate, load_model, set_seed


class PeakRSSMonitor:
    """Периодически измерять RSS процесса и сохранять максимум."""

    def __init__(self, interval_sec: float = 0.01) -> None:
        self._process = psutil.Process()
        self._interval_sec = interval_sec
        self._peak_bytes = self._process.memory_info().rss
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._sample, daemon=True)

    def _sample(self) -> None:
        while not self._stop_event.wait(self._interval_sec):
            self._peak_bytes = max(
                self._peak_bytes, self._process.memory_info().rss
            )

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> float:
        self._stop_event.set()
        self._thread.join()
        self._peak_bytes = max(self._peak_bytes, self._process.memory_info().rss)
        return self._peak_bytes / (1024**2)


def synchronize_device(model) -> None:
    """Дождаться завершения асинхронных операций ускорителя перед таймером."""
    device_type = model.device.type
    if device_type == "cuda":
        torch.cuda.synchronize(model.device)
    elif device_type == "mps":
        torch.mps.synchronize()


def main() -> None:
    params = load_params()
    prompt = params["bench"]["prompt"]
    set_seed(params["generate"]["seed"])
    rss_monitor = PeakRSSMonitor()
    rss_monitor.start()

    t0 = time.perf_counter()
    tokenizer, model = load_model(params)
    load_time = time.perf_counter() - t0

    for _ in range(params["bench"]["warmup_runs"]):
        generate(tokenizer, model, params, prompt)

    speeds = []
    for _ in range(params["bench"]["measure_runs"]):
        synchronize_device(model)
        t0 = time.perf_counter()
        _, n_tokens = generate(tokenizer, model, params, prompt)
        synchronize_device(model)
        elapsed = time.perf_counter() - t0
        speeds.append(n_tokens / elapsed)

    peak_rss_mb = rss_monitor.stop()

    # Медиана устойчивее среднего к одиночному выбросу.
    report = {
        "model": params["model"]["name"],
        "device": str(model.device),
        "dtype": params["model"]["dtype"],
        "load_time_sec": round(load_time, 2),
        "tokens_per_sec": round(statistics.median(speeds), 2),
        "tokens_per_sec_all": [round(s, 2) for s in speeds],
        "peak_rss_mb": round(peak_rss_mb, 1),
    }

    Path("docs").mkdir(exist_ok=True)
    Path("docs/bench.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
