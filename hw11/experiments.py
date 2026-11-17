"""Run live, bounded experiments against the named kind cluster."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
import os
from pathlib import Path
import subprocess
import threading
import time
from urllib.parse import urlencode
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent
RESULTS = Path(os.environ.get("HW11_RESULTS", str(ROOT / "results"))).resolve()
os.environ.setdefault("KUBECONFIG", os.environ.get("HW11_KUBECONFIG", str(ROOT / ".kubeconfig")))
K = ["kubectl", "--context", "kind-hw11"]
N = [*K, "-n", "hw11"]
H = ["helm", "--kube-context", "kind-hw11", "-n", "hw11"]
PORT = 19091
OUTPUT_LOCK = threading.Lock()


def command(*args, **kwargs):
    return subprocess.run(args, cwd=ROOT, text=True, check=True, capture_output=True, **kwargs).stdout


def kubectl(*args):
    return command(*N, *args)


def get(*args):
    return json.loads(kubectl("get", *args, "-o", "json"))


def write(name, data):
    (RESULTS / name).write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def append(name, data):
    with OUTPUT_LOCK, (RESULTS / name).open("a") as dest:
        dest.write(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")


def event(phase, action, **fields):
    print(phase, action, fields, flush=True)
    append("events.jsonl", {"phase":phase,"event":action,"ts":time.time(), **fields})


def release(version="A", early=False, bad=False, hpa=False):
    options = [f"modelVersion={version}", f"earlyReady={str(early).lower()}",
               f"hpa.enabled={str(hpa).lower()}"]
    if bad:
        options.append("artifactSHAOverride=deliberately-wrong")
    return command(*H, "upgrade", "lab", "chart", "--reset-values",
                   *[arg for setting in options for arg in ("--set", setting)])


def wait_rollout():
    return kubectl("rollout", "status", "deployment/inference", "--timeout=110s")


def pods():
    return get("pods", "-l", "app=inference")["items"]


def ready(obj):
    return any(c["type"] == "Ready" and c["status"] == "True"
               for c in obj.get("status",{}).get("conditions",[]))


def version(obj):
    return next(e["value"] for e in obj["spec"]["containers"][0]["env"] if e["name"] == "MODEL_VERSION")


def ready_pods():
    return [p for p in pods() if ready(p) and not p["metadata"].get("deletionTimestamp")]


def monitor_snapshot(phase):
    items = get("pod,endpointslice,deploy,hpa")["items"]
    selected = [p for p in items if p["kind"]=="Pod" and p["metadata"]["labels"].get("app")=="inference"]
    slices = [p for p in items if p["kind"]=="EndpointSlice"
              and p["metadata"]["labels"].get("kubernetes.io/service-name") in ("inference","inference-affinity")]
    autoscaler = next((p for p in items if p["kind"]=="HorizontalPodAutoscaler"), {})
    append("timeline.jsonl", {
        "phase":phase,"ts":time.time(),
        "pods":[{"name":p["metadata"]["name"],"uid":p["metadata"]["uid"],
                 "version":version(p), "ready":ready(p),
                 "created":p["metadata"]["creationTimestamp"],"ip":p["status"].get("podIP"),
                 "deleting":p["metadata"].get("deletionTimestamp"),
                 "restarts":sum(c["restartCount"] for c in p["status"].get("containerStatuses",[]))}
                for p in selected],
        "endpoints":[{"service":s["metadata"]["labels"]["kubernetes.io/service-name"],
                      "pod":ep.get("targetRef",{}).get("name"),"ip":ep["addresses"][0],
                      **ep["conditions"]} for s in slices for ep in s["endpoints"]],
        "hpa":autoscaler.get("status",{})})


def prom(path, **params):
    query = "?" + urlencode(params) if params else ""
    with urlopen(f"http://127.0.0.1:{PORT}/api/v1/{path}{query}",timeout=4) as response:
        data = json.load(response)
    if data["status"] != "success":
        raise RuntimeError(data)
    return data["data"]


@contextmanager
def prom_forward():
    process = subprocess.Popen([*N,"port-forward","svc/prometheus",f"{PORT}:9090"],
                               stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    try:
        for _ in range(20):
            try:
                prom("alerts")
                break
            except OSError:
                time.sleep(.5)
        else:
            raise RuntimeError("Prometheus did not start")
        yield
    finally:
        process.terminate()
        process.wait()


@contextmanager
def observe(phase, alerts=False, interval=1.0):
    stop = threading.Event()

    def watch():
        while not stop.is_set():
            try:
                monitor_snapshot(phase)
                if alerts:
                    data = prom("alerts")
                    append("alert-states.jsonl",{"phase":phase,"ts":time.time(),**data})
            except (OSError,subprocess.CalledProcessError) as exc:
                event(phase,"observer_error",detail=str(exc))
            stop.wait(interval)

    with ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(watch)
        try:
            yield
        finally:
            stop.set()
            future.result()


def schedule(phase, duration, rate, pattern="even", cpu=0, gap=60):
    rows = []
    for i in range(int(duration * rate)):
        block, n = divmod(i, 5)
        client = (0 if n < 4 else 1 + block % 3) if pattern == "hot" else i % 4
        prefix = f"cold-{i}" if i % 13 == 0 else f"shared-{i%4}"
        rows.append({"id":f"{phase}-{i:04d}","phase":phase,"client_index":client,
                     "offset_s":i/rate,"payload":{"prompt":f"{prefix}| question {i:04d}",
                     "session_id":f"client-{client}","stream":True,"chunks":3,"chunk_ms":gap,"cpu_ms":cpu}})
    return rows


def dialog(phase, client=1, offset=0, *, marker="", chunks=3, gap=60, notify=False):
    history = [{"role":"user","content":marker},{"role":"assistant","content":"Принято"}] if marker else []
    return {"id":f"{phase}-{client}","phase":phase,"client_index":client,"offset_s":offset,
            "notify_first":notify,"payload":{"prompt":"geo| Продолжи диалог","stream":True,"chunks":chunks,
            "chunk_ms":gap,"history":history,"session_id":marker or phase}}


def send(host, rows, epoch, on_first=None):
    client = rows[0]["client_index"]
    args = [*N,"exec","-i",f"client-{client}","--","python","/app/client.py",host,str(epoch)]
    with subprocess.Popen(args,cwd=ROOT,text=True,stdin=subprocess.PIPE,stdout=subprocess.PIPE) as proc:
        proc.stdin.write(json.dumps(rows))
        proc.stdin.close()
        records = []
        for line in proc.stdout:
            row = json.loads(line)
            if row.get("event") == "first":
                event(row["id"],"first_chunk",pod=row["pod"],client_ts=row["ts"])
                if on_first:
                    on_first(row)
            else:
                row["service"] = host
                append("requests.jsonl",row)
                records.append(row)
        if proc.wait():
            raise RuntimeError(f"client {client} exited {proc.returncode}")
        return records


def traffic(host, rows, action=None, action_after=0, epoch=None):
    epoch = epoch or time.time_ns() + 2_000_000_000
    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = []
        for client in range(4):
            local = [r for r in rows if r["client_index"]==client]
            if local:
                futures.append(executor.submit(send,host,local,epoch))
        if action is not None:
            time.sleep(max(0,(epoch - time.time_ns())/1e9 + action_after))
            action()
        result = [r for f in futures for r in f.result()]
    if len(result) != len(rows):
        raise RuntimeError(f"Expected {len(rows)} rows, got {len(result)}")
    return result



@contextmanager
def follow_logs(phase, objects):
    path = RESULTS / "server"
    path.mkdir(exist_ok=True)
    handles = []
    try:
        for obj in objects:
            name = obj["metadata"]["name"]
            out = (path / f"{phase}-{name}.log").open("w")
            proc = subprocess.Popen([*N,"logs","-f",name,"--since=10s"],
                                    stdout=out,stderr=subprocess.STDOUT)
            handles.append((proc,out))
        yield
    finally:
        for proc,out in handles:
            proc.terminate()
            proc.wait()
            out.close()


def capture_logs(phase):
    for pod in pods():
        name = pod["metadata"]["name"]
        try:
            output = kubectl("logs",name,"--since=400s")
        except subprocess.CalledProcessError:
            continue
        path = RESULTS / "server"
        path.mkdir(exist_ok=True)
        (path / f"{phase}-{name}.log").write_text(output)


def wait_until(predicate, timeout=120):
    stop = time.monotonic() + timeout
    while time.monotonic() < stop:
        value = predicate()
        if value:
            return value
        time.sleep(1)
    raise RuntimeError("timed out waiting for convergence")


def phase_a():
    for phase, early in (("a-early",True),("a-fixed",False)):
        with observe(phase):
            def deploy():
                event(phase,"upgrade",early_ready=early)
                release(early=early)
            rows = traffic("inference",schedule(phase,32,3),deploy,1)
            event(phase,"outcome",unwarmed=sum(r["warmed"]=="false" for r in rows))
            wait_rollout()
            capture_logs(phase)
    phase = "a-rollout"
    old = ready_pods()
    epoch = time.time_ns() + 2_000_000_000
    with observe(phase), follow_logs("a-retiring", old), ThreadPoolExecutor(max_workers=4) as executor:
        # First stream crosses initiation. Two later streams occupy both old replicas at drain.
        streams = [
            executor.submit(send,old[0]["status"]["podIP"],
                            [dialog("a-rollout-cross",2,chunks=12,gap=850,notify=True)],epoch)
        ]
        for i,p in enumerate(old):
            streams.append(executor.submit(send,p["status"]["podIP"],
                           [dialog(f"a-rollout-drain-{i}",i,offset=18,chunks=12,gap=1000)],epoch))
        def upgrade():
            event(phase,"upgrade",target="B",from_pods=[p["metadata"]["name"] for p in old])
            release("B")
        rows = traffic("inference",schedule(phase,55,.5),upgrade,2,epoch)
        rows.extend(r for f in streams for r in f.result())
        event(phase,"outcomes", **{o:sum(r["outcome"]==o for r in rows)
                                    for o in ("ok","http_error","rejected","aborted","timeout")})
        wait_rollout()
        capture_logs(phase)
        if any(r["outcome"] != "ok" for r in rows):
            event(phase,"unexpected_outcome",rows=[r["id"] for r in rows if r["outcome"]!="ok"])
    phase_a_recovery()


def phase_a_recovery():
    # Put A in the last known good revision so rollback can be explicit.
    release()
    wait_rollout()
    good_history = json.loads(command(*H,"history","lab","-o","json"))
    good_revision = good_history[-1]["revision"]
    phase = "a-bad"
    with observe(phase):
        def bad():
            event(phase,"invalid_B",expected_sha="deliberately-wrong")
            release("B",bad=True)
        traffic("inference",schedule(phase,25,2),bad,1)
        capture_logs(phase)
        (RESULTS/"bad-deployment.txt").write_text(kubectl("describe","deployment","inference"))
        event(phase,"rollback",revision=good_revision)
        command(*H,"rollback","lab",str(good_revision),"--wait","--timeout","110s")
        traffic("inference",schedule("a-rollback",8,2))
    phase = "a-kill"
    victim = ready_pods()[0]
    container_id = victim["status"]["containerStatuses"][0]["containerID"].split("://")[1]
    victim_name = victim["metadata"]["name"]
    marker = "GEONAMES-ALPHA-714"
    previous = traffic(victim["status"]["podIP"],[dialog("a-dialog-before",marker=marker)])[0]
    with observe(phase), ThreadPoolExecutor(max_workers=1) as executor:
        def kill(row):
            event(phase,"forced_stop",pod=row["pod"],container_id=container_id)
            command("docker","exec","hw11-control-plane","crictl","stop","--timeout","0",container_id)
        interrupted = executor.submit(send,victim["status"]["podIP"],
                        [dialog("a-kill-stream",client=1,chunks=12,gap=850,notify=True)],
                        time.time_ns()+2_000_000_000,kill)
        traffic("inference",schedule(phase,28,3))
        event(phase,"stream_outcome",outcome=interrupted.result()[0]["outcome"])
        original_uid = victim["metadata"]["uid"]
        wait_until(lambda: any(p["metadata"]["uid"] == original_uid and
                               p["status"]["containerStatuses"][0]["restartCount"] >= 1
                               for p in ready_pods()))
        (RESULTS/"victim-previous.log").write_text(kubectl("logs",victim_name,"--previous"))
        event(phase,"delete_pod",pod=victim_name,uid=original_uid)
        kubectl("delete","pod",victim_name,"--wait=false")
        before_names = {p["metadata"]["name"] for p in ready_pods()} | {victim_name}
        replacement = wait_until(lambda: next((p for p in ready_pods()
                                  if p["metadata"]["name"] not in before_names),None))
        event(phase,"replacement_ready",old=previous["pod"],new=replacement["metadata"]["name"],
              uid=replacement["metadata"]["uid"])
        traffic(replacement["status"]["podIP"],[
            dialog("a-dialog-after",0,marker=marker),dialog("a-dialog-after",1,marker="GEONAMES-BETA-392")])
        capture_logs(phase)


def reset_cache():
    for p in ready_pods():
        kubectl("exec",p["metadata"]["name"],"--","python","-c",
                "import urllib.request as u; u.urlopen(u.Request('http://127.0.0.1:8080/internal/clear-cache', method='POST')).close()")


def series(expr, when=None):
    kwargs = {"query":expr}
    if when is not None:
        kwargs["time"] = str(when)
    return prom("query",**kwargs)["result"]


def phase_b():
    release()
    wait_rollout()
    write("routing-services.json",get("svc","inference","inference-affinity"))
    write("client-pods.json", [{"name":p["metadata"]["name"],"ip":p["status"]["podIP"],"node":p["spec"]["nodeName"]}
                              for p in get("pods")["items"] if p["metadata"]["name"].startswith("client-")])
    (RESULTS/"network.txt").write_text(command(*K,"-n","kube-system","get","configmap","kube-proxy","-o","yaml"))
    for repetition in range(1,4):
        # Reverse paired order in the middle to reduce systematic order effects.
        for pattern in ("even","hot"):
            for policy in (("affinity","plain") if repetition == 2 else ("plain","affinity")):
                phase = f"b-{pattern}-{policy}-{repetition}"
                if (RESULTS / f"{phase}-prom.json").exists():
                    event(phase,"skip_completed")
                    continue
                host = "inference-affinity" if policy == "affinity" else "inference"
                reset_cache()
                time.sleep(4)
                keys = ("hw11_ttfc_seconds_bucket","hw11_response_seconds_bucket",
                        "hw11_queue_seconds_bucket","hw11_requests_total")
                snapshot = lambda: {key:series(key) for key in keys}
                before = snapshot()
                epoch = time.time_ns() + 2_000_000_000
                event(phase,"measurement_start",scheduled_epoch_ns=epoch,duration_seconds=120,rate=5)
                with observe(phase,interval=6):
                    rows = traffic(host,schedule(phase,120,5,pattern),epoch=epoch)
                ended = max(r["ended_wall_ns"] for r in rows)/1e9
                time.sleep(4)
                end = time.time()
                window = f"{int(end-epoch/1e9)+3}s"
                expr = f"histogram_quantile(0.95, sum by (le) (increase(hw11_ttfc_seconds_bucket[{window}])))"
                write(f"{phase}-prom.json",{"before":before,"after":snapshot(),
                       "planned_start":epoch/1e9,"observed_end":ended,"query_at":end,
                       "promql":expr,"quantile":series(expr,end)})
                capture_logs(phase)
                event(phase,"measurement_end",sent=len(rows),ok=sum(r["outcome"]=="ok" for r in rows))


def phase_c():
    phase = "c-hpa"
    release(hpa=True)
    wait_rollout()
    wait_until(lambda: len(ready_pods()) == 2 and len(pods()) == 2)
    (RESULTS/"hpa.yaml").write_text(kubectl("get","hpa","inference","-o","yaml"))
    write("resource-metrics-start.json",json.loads(command(*K,"get","--raw","/apis/metrics.k8s.io/v1beta1/namespaces/hw11/pods")))
    with observe(phase,alerts=True,interval=2):
        start = time.time()
        time.sleep(7)
        # Populate each of the four IP bindings while there are still two replicas.
        traffic("inference-affinity",
                [dialog("c-affinity-seed",i) for i in range(4)])
        with ThreadPoolExecutor(max_workers=1) as executor:
            anchor = executor.submit(traffic,"inference-affinity",
                                     schedule("c-affinity-anchor",86,.5))
            event(phase,"load_start",rate=12,cpu_ms=130,anchor_rate=.5)
            traffic("inference",schedule(phase,86,12,cpu=130,gap=120))
            anchor.result()
        event(phase,"load_end")
        metric = lambda: len(ready_pods()) == 3
        wait_until(metric,30)
        # New connections still originate from the same dominant client during this comparison.
        traffic("inference-affinity",schedule("c-hpa-hot",30,10,"hot",cpu=130,gap=120))
        event(phase,"hot_load_end")
        wait_until(lambda: len(pods()) == 2 and len(ready_pods()) == 2,180)
        event(phase,"returned_to_two")
        time.sleep(18)
    capture_logs(phase)
    end = time.time()
    queries = {
        "process_cpu":"rate(process_cpu_seconds_total{job=\"inference\"}[15s])",
        "running":"hw11_running",
        "waiting":"hw11_waiting",
        "ready":"sum(kube_pod_status_ready{condition=\"true\"})",
        "alerts":"ALERTS",
        "rss":"process_resident_memory_bytes{job=\"inference\"}",
        "terminal":"sum by(pod,outcome)(rate(hw11_requests_total[15s]))",
        "p95":"histogram_quantile(0.95, sum by(le)(rate(hw11_ttfc_seconds_bucket[24s])))",
    }
    write("hpa-monitoring.json",{k:prom("query_range",query=v,start=start,end=end,step=3)
                                for k,v in queries.items()})
    write("resource-metrics-end.json",json.loads(command(*K,"get","--raw","/apis/metrics.k8s.io/v1beta1/namespaces/hw11/pods")))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phases",nargs="+",choices=["a","recovery","b","c"])
    args = parser.parse_args()
    RESULTS.mkdir(exist_ok=True)
    for phase in args.phases:
        try:
            if phase in ("a","recovery"):
                {"a":phase_a,"recovery":phase_a_recovery}[phase]()
            else:
                with prom_forward():
                    {"b":phase_b,"c":phase_c}[phase]()
        except subprocess.CalledProcessError as err:
            print(err.stdout,err.stderr,flush=True)
            raise


if __name__ == "__main__":
    main()
