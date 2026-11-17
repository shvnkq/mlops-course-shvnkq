"""Archive monitoring series for the exact 120-second routing windows."""
from experiments import RESULTS, prom, prom_forward, write

import json


METRICS = {
    "waiting":"hw11_waiting", "running":"hw11_running",
    "cpu":"rate(process_cpu_seconds_total{job=\"inference\"}[15s])",
    "rss":"process_resident_memory_bytes{job=\"inference\"}",
    "ready":"sum(kube_pod_status_ready{condition=\"true\"})",
}


def main():
    windows = sorted(RESULTS.glob("b-*-prom.json"))
    if len(windows)!=12:
        raise SystemExit(f"Expected 12 routing windows, received {len(windows)}")
    data = {}
    with prom_forward():
        write("prometheus-targets.json",prom("targets",state="active"))
        for path in windows:
            phase = path.name.removesuffix("-prom.json")
            window = json.loads(path.read_text())
            first, last = window["planned_start"], window["observed_end"]
            data[phase] = {name:prom("query_range",query=expr,start=first,end=last,step=3)
                           for name,expr in METRICS.items()}
    write("routing-monitoring.json",data)


if __name__ == "__main__":
    main()
