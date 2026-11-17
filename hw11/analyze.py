"""Generate plots and the submission report from raw client and cluster observations."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
import html
import json
import math
from pathlib import Path
import re
import statistics

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from experiments import ROOT, RESULTS

plt.rcParams.update({"font.size":11,"axes.titleweight":"bold","axes.spines.top":False,
                     "axes.spines.right":False,"svg.fonttype":"none","figure.dpi":150})
BLUE, AMBER, TEAL = "#2261ae", "#be5928", "#167969"
FIGURES = ROOT / "figures"


def read(name):
    return json.loads((RESULTS/name).read_text())


def lines(name):
    return [json.loads(row) for row in (RESULTS/name).read_text().splitlines()]


def percentile(values,p=.95):
    data = sorted(values)
    if not data:
        return None
    x = (len(data)-1)*p
    left = int(x)
    return data[left] + (x-left)*(data[math.ceil(x)]-data[left])


def elapsed(row,start,end):
    return (row[end]-row[start])/1e9


def summarize(rows):
    ok = [r for r in rows if r["outcome"]=="ok"]
    counts = Counter(r["outcome"] for r in rows)
    result = {**{k:counts[k] for k in ("ok","rejected","http_error","aborted","timeout")},
              "planned":len(rows),"sent":sum(r["sent_ns"] is not None for r in rows),
              "completed":sum(r["ended_ns"] is not None for r in rows),
              "errors_pct":100*(len(rows)-len(ok))/len(rows),
              "timeouts_pct":100*counts["timeout"]/len(rows),
              "5xx":sum((r["status"] or 0)>=500 for r in rows),
              "confirmed_unwarmed":sum(r["warmed"]=="false" for r in ok),
              "hits_pct":100*sum(r["cache_hit"] is True for r in ok)/len(ok) if ok else None}
    sets = {"ttfc":[elapsed(r,"sent_ns","first_ns") for r in ok],
            "total":[elapsed(r,"sent_ns","ended_ns") for r in ok],
            "queue":[r["queue_seconds"] for r in ok],
            "gap":[gap for r in ok for gap in r["inter_chunk_seconds"]],
            "send_lag":[elapsed(r,"scheduled_ns","sent_ns") for r in rows if r["sent_ns"] is not None]}
    for name,values in sets.items():
        result[name] = {"n":len(values),"p50":percentile(values,.5),"p95":percentile(values)}
    result["peak_send_lag_ms"] = 1000*max(sets["send_lag"],default=0)
    return result


def histogram_quantile(buckets, quantile=.95):
    """Prometheus classic histogram interpolation for finite buckets."""
    target = buckets[math.inf]*quantile
    lower_bound, previous = 0.0, 0.0
    for upper_bound,count in sorted(buckets.items()):
        if math.isinf(upper_bound):
            return lower_bound
        if count >= target and count > previous:
            return lower_bound + (upper_bound-lower_bound)*(target-previous)/(count-previous)
        lower_bound,previous = upper_bound,count
    return None


def histogram_delta(phase):
    snapshots = read(f"{phase}-prom.json")
    key = "hw11_ttfc_seconds_bucket"
    before = {(r["metric"]["pod"],r["metric"]["le"]):float(r["value"][1]) for r in snapshots["before"][key]}
    buckets = defaultdict(float)
    for r in snapshots["after"][key]:
        bound = r["metric"]["le"]
        buckets[float(bound)] += float(r["value"][1])-before[(r["metric"]["pod"],bound)]
    expression = snapshots["quantile"]
    return {"count":int(buckets[math.inf]),"bucket_p95":histogram_quantile(buckets),
            "range_p95":float(expression[0]["value"][1]) if expression else None,
            "expression":snapshots["promql"],"time":snapshots["query_at"]}


def phase_order():
    return [f"b-{dist}-{policy}-{i}" for dist in ("even","hot")
            for policy in ("plain","affinity") for i in range(1,4)]


def save(fig,name):
    FIGURES.mkdir(exist_ok=True)
    for suffix in ("svg","png"):
        fig.savefig(FIGURES/f"{name}.{suffix}",bbox_inches="tight")
    plt.close(fig)


def plot_a(by_phase,timeline,events):
    phases = ("a-early","a-fixed","a-rollout")
    fig, axes = plt.subplots(3,1,figsize=(11,8.7),layout="constrained")
    for index,(phase,ax) in enumerate(zip(phases,axes)):
        ts = [t for t in timeline if t["phase"]==phase]
        anchor = next(e["ts"] for e in events if e["phase"]==phase and e["event"]=="upgrade")
        xs = [t["ts"]-anchor for t in ts]
        ax.step(xs,[sum(p["ready"] for p in t["pods"]) for t in ts],where="post",
                color=BLUE,label="Pod Ready",linewidth=2.5)
        ax.step(xs,[sum(e["ready"] for e in t["endpoints"] if e["service"]=="inference") for t in ts],
                where="post",color=TEAL,linestyle="--",label="EndpointSlice Ready")
        ax.step(xs,[sum(p["ready"] and p["version"]=="B" for p in t["pods"]) for t in ts],
                where="post",color=AMBER,linestyle=":",label="Ready B")
        rows = by_phase[phase]
        if index==2:
            rows = rows+by_phase["a-rollout-cross"]+by_phase["a-rollout-drain-0"]+by_phase["a-rollout-drain-1"]
            for i,row in enumerate(r for r in rows if r["phase"]!=phase):
                ax.plot([row["sent_wall_ns"]/1e9-anchor,row["ended_wall_ns"]/1e9-anchor],
                        [-.15-i*.18]*2, linewidth=4,color=TEAL,alpha=.8,
                        label="Длинный поток A" if i==0 else None)
        unwarmed = [r["sent_wall_ns"]/1e9-anchor for r in rows if r["warmed"]=="false"]
        if unwarmed:
            ax.scatter(unwarmed,[-.1]*len(unwarmed),s=12,color="#b32931",label="Запрос до прогрева")
        ax.set(title=("Дефект · HTTP раньше прогрева","Исправление · readiness ждёт прогрев",
                      "Штатный A → B · активные потоки A")[index],
               ylabel="Реплики, шт.",xlabel="Секунды от команды upgrade",ylim=(-.65,3.4))
        ax.axvline(0,color="#777777",linewidth=1)
        ax.grid(axis="y",alpha=.2)
        ax.legend(loc="upper right",ncol=2,fontsize=8,frameon=False)
    save(fig,"01-warmup-rollout")


def plot_b_pods(by_phase,stats):
    phase = max((f"b-hot-affinity-{i}" for i in range(1,4)),
                key=lambda p: stats[p]["errors_pct"])
    rows = by_phase[phase]
    names = sorted({item["metric"]["pod"] for item in read("routing-monitoring.json")[phase]["running"]["result"]})
    fig,axes = plt.subplots(2,1,figsize=(11,7),sharex=True,layout="constrained")
    for i,name in enumerate(names):
        observed = [r for r in rows if r["pod"]==name and r["outcome"]=="ok"]
        rejected = [r for r in rows if r["pod"]==name and r["outcome"]=="rejected"]
        color = (BLUE,AMBER)[i]
        label=f"{name} · {len(observed)} успешных, {len(rejected)} отказов"
        axes[0].scatter([r["offset_s"] for r in observed],
                        [1000*elapsed(r,"sent_ns","first_ns") for r in observed],
                        s=9,alpha=.55,color=color,label=label)
        axes[1].scatter([r["offset_s"] for r in observed],[1000*r["queue_seconds"] for r in observed],
                        s=9,alpha=.55,color=color)
    axes[0].set(title=f"TTFC и очередь по Pod · {phase} · 5 запросов/с",ylabel="TTFC, мс")
    axes[1].set(ylabel="Очередь, мс",xlabel="Секунды от запланированного начала")
    axes[0].legend(frameon=False,loc="upper right",fontsize=8)
    for ax in axes:
        ax.grid(alpha=.2)
    save(fig,"02-per-pod")
    return phase


def plot_b_runs(stats):
    fig,axes = plt.subplots(2,2,figsize=(11,7),sharey="row",layout="constrained")
    for row,metric in enumerate(("ttfc","errors_pct")):
        for col,dist in enumerate(("even","hot")):
            ax = axes[row][col]
            for policy,color,delta in (("plain",BLUE,-.12),("affinity",AMBER,.12)):
                group = [stats[f"b-{dist}-{policy}-{rep}"] for rep in range(1,4)]
                values = [1000*x[metric]["p95"] if row==0 else x[metric] for x in group]
                ax.plot([i+delta for i in (1,2,3)],values,"o-",color=color,
                        label="Обычный Service" if policy=="plain" else "ClientIP")
            ax.set(xticks=[1,2,3],xlabel="Повтор",
                  ylabel=("TTFC p95, мс" if row==0 else "Ошибки, %"),
                  title=("Равномерно · четыре источника" if dist=="even" else "80% от одного источника"))
            ax.grid(alpha=.2)
            if row==0:
                ax.legend(fontsize=8,frameon=False)
    save(fig,"03-routing-comparison")


def plot_c(by_phase,timeline,events):
    phase = "c-hpa"
    rows = by_phase[phase]+by_phase["c-hpa-hot"]+by_phase["c-affinity-anchor"]
    ts = [t for t in timeline if t["phase"]==phase]
    anchor = next(e["ts"] for e in events if e["phase"]==phase and e["event"]=="load_start")
    xs = [t["ts"]-anchor for t in ts]
    fig,axes = plt.subplots(2,1,figsize=(11,7),sharex=True,layout="constrained")
    ax = axes[0]
    ax.step(xs,[t["hpa"].get("desiredReplicas",0) for t in ts],where="post",color=BLUE,label="HPA desired")
    ax.step(xs,[sum(p["ready"] for p in t["pods"]) for t in ts],where="post",color=TEAL,label="Pod Ready")
    ax.step(xs,[sum(not p.get("deleting") for p in t["pods"]) for t in ts],where="post",
            color=AMBER,linestyle="--",label="Pod создан")
    ax.set(title="HPA · 100m request на Pod · target 55% · 130 мс CPU на запрос",
           ylabel="Реплики, шт.",ylim=(1.7,3.5),yticks=[2,3])
    ax.legend(loc="upper right",frameon=False)
    ax = axes[1]
    cpu = []
    for t in ts:
        cpu.append(next((m.get("resource",{}).get("current",{}).get("averageUtilization",math.nan)
                         for m in t["hpa"].get("currentMetrics",[]) if m.get("resource",{}).get("name")=="cpu"),math.nan))
    ax.step(xs,cpu,where="post",color=BLUE,label="CPU HPA, % request")
    ax.axhline(55,color="#777777",linestyle=":",label="CPU target")
    ax.set(ylabel="CPU, % от requests",xlabel="Секунды от начала нагрузки")
    rate_axis = ax.twinx()
    bins = Counter(int((r["sent_wall_ns"]/1e9-anchor)//5)*5 for r in rows)
    positions = range(0,max(5,5*math.ceil(xs[-1]/5)),5)
    rate_axis.bar(positions,[bins[x]/5 for x in positions],align="edge",width=5,color=AMBER,
                  alpha=.25,label="Отправлено, запросов/с (5 с)")
    rate_axis.set_ylabel("Запросов/с")
    rate_axis.set_ylim(0,14)
    lines_a,labels_a=ax.get_legend_handles_labels()
    lines_b,labels_b=rate_axis.get_legend_handles_labels()
    ax.legend(lines_a+lines_b,labels_a+labels_b,loc="upper right",frameon=False,fontsize=8)
    for ax in axes:
        ax.grid(axis="y",alpha=.2)
    save(fig,"04-hpa")

def utc(timestamp):
    return datetime.fromtimestamp(timestamp,timezone.utc).strftime("%H:%M:%S UTC")


def table(headers, rows):
    esc = lambda value: html.escape(str(value))
    head = "".join(f"<th scope='col'>{esc(h)}</th>" for h in headers)
    body = "".join("<tr>"+"".join(f"<td>{esc(cell)}</td>" for cell in row)+"</tr>" for row in rows)
    return f"<div class='table'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def figure(name, caption):
    return f'<figure><img src="figures/{name}.svg" alt="{html.escape(caption)}"><figcaption>{caption}</figcaption></figure>'


def ms(summary,key="ttfc"):
    t=summary[key]
    return "—" if t["n"]==0 else f'{1000*t["p50"]:.0f} / {1000*t["p95"]:.0f} ({t["n"]})'


def responses_table(stats, phases, describe):
    return table(["Сценарий","План / отправлено","Завершено¹ / OK","429","5xx","Оборвано","Timeout",
                  "Ошибки / timeout, %","TTFC p50/p95, мс (n)","Весь ответ p50/p95, мс (n)","Inter-chunk p50/p95, мс (n)"],
                 [[describe(phase),f'{s["planned"]} / {s["sent"]}',f'{s["completed"]} / {s["ok"]}',
                  s["rejected"],s["5xx"],s["aborted"],s["timeout"],f'{s["errors_pct"]:.1f} / {s["timeouts_pct"]:.1f}',
                  ms(s),ms(s,"total"),ms(s,"gap")] for phase in phases for s in (stats[phase],)])


def groups(rows):
    distributed = defaultdict(list)
    for row in rows:
        distributed[row["pod"] or "без Pod"].append(row)
    return distributed


def live_load_witness(pod_series):
    values = lambda name: {item["metric"]["pod"]:{t:float(v) for t,v in item["values"]}
                           for item in pod_series[name]["result"]}
    waiting,running = values("waiting"),values("running")
    witnesses = []
    for hot,queue in waiting.items():
        for idle,active in running.items():
            if hot == idle:
                continue
            witnesses += [(t,hot,depth,idle) for t,depth in queue.items() if depth>=1
                          and active.get(t)==0 and waiting[idle].get(t)==0]
    return sorted(witnesses)


def report(by_phase, stats, timeline, events, plotted_phase):
    event = lambda phase,name: next(e for e in events if e["phase"]==phase and e["event"]==name)
    a_early,a_fixed = [stats[p] for p in ("a-early","a-fixed")]
    version_a = by_phase["a-rollback"][0]["runtime_sha256"]
    version_b = next(r["runtime_sha256"] for r in by_phase["a-rollout"] if r["version"]=="B")
    crossing = by_phase["a-rollout-cross"][0]
    upgrade = event("a-rollout","upgrade")["ts"]
    cut = by_phase["a-kill-stream"][0]
    killed = event("a-kill","forced_stop")["ts"]
    before, after = by_phase["a-dialog-before"][0], by_phase["a-dialog-after"]
    a_timeline = [t for t in timeline if t["phase"]=="a-rollout"]
    warm_times = []
    for pod in {p["name"] for t in a_timeline for p in t["pods"] if p["version"]=="B"}:
        created = next(p["created"] for t in a_timeline for p in t["pods"] if p["name"]==pod)
        birth = datetime.fromisoformat(created.replace("Z","+00:00")).timestamp()
        seen = next(t["ts"] for t in a_timeline if any(p["name"]==pod and p["ready"] for p in t["pods"]))
        warm_times.append((pod, f"{birth-upgrade:.1f}",f"{seen-upgrade:.1f}",f"{seen-birth:.1f}"))
    kill_timeline = [(t["ts"],p) for t in timeline if t["phase"]=="a-kill" and t["ts"]>=killed
                     for p in t["pods"] if p["name"]==cut["pod"]]
    not_ready = next(t for t,p in kill_timeline if not p["ready"])
    recovered = next(t for t,p in kill_timeline if p["ready"] and p["restarts"]>0)
    retired = [json.loads(l) for p in (RESULTS/"server").glob("a-retiring-*.log")
               for l in p.read_text().splitlines() if l.startswith("{")]
    active_drains = [r for r in retired if r["event"]=="drain_started" and r["running"]>0]
    b_stats = {p: histogram_delta(p) for p in phase_order()}
    routing = read("routing-monitoring.json")
    witness = live_load_witness(routing[plotted_phase])
    ranges = []
    for phase in phase_order():
        src = defaultdict(Counter)
        for row in by_phase[phase]:
            src[row["source_ip"]][row["pod"]] += 1
        for ip,dest in sorted(src.items()):
            ranges.append([phase,ip,", ".join(f"{pod}: {count}" for pod,count in sorted(dest.items(),key=str))])
    hot_conclusion = []
    for i in range(1,4):
        p,a = (stats[f"b-hot-{policy}-{i}"] for policy in ("plain","affinity"))
        hot_conclusion.append([i,ms(a),ms(p),f'{a["errors_pct"]:.1f} → {p["errors_pct"]:.1f}',
                               f'{a["hits_pct"]:.1f} → {p["hits_pct"]:.1f}'])
    spread_table = []
    for phase in phase_order():
        spread_table.append([phase,stats[phase]["peak_send_lag_ms"],
                             " / ".join(str(len(rs)) for _,rs in sorted(groups(by_phase[phase]).items()))])
    balanced = min((f"b-even-affinity-{i}" for i in range(1,4)),key=lambda p: abs(.5-max(map(len,groups(by_phase[p]).values()))/len(by_phase[p])))
    balanced_counts = sorted((pod,len(rs)) for pod,rs in groups(by_phase[balanced]).items())
    c_timeline = [t for t in timeline if t["phase"]=="c-hpa"]
    start = event("c-hpa","load_start")["ts"]
    hot_start = min(r["sent_wall_ns"] for r in by_phase["c-hpa-hot"])/1e9
    hot_end = event("c-hpa","hot_load_end")["ts"]
    base = {p["name"] for p in c_timeline[0]["pods"]}
    new_t, new_pod = next((t["ts"],p) for t in c_timeline for p in t["pods"] if p["name"] not in base)
    new_ready = next(t["ts"] for t in c_timeline if any(p["name"]==new_pod["name"] and p["ready"] for p in t["pods"]))
    lowered = next(t["ts"] for t in c_timeline if t["ts"]>hot_end and t["hpa"].get("desiredReplicas")==2)
    two = event("c-hpa","returned_to_two")["ts"]
    c_hot_counts = Counter(r["pod"] for r in by_phase["c-hpa-hot"])
    anchor = {r["source_ip"]:r["pod"] for r in by_phase["c-affinity-seed"]}
    anchor_trace = [[ip,pod,Counter(r["pod"] for r in by_phase["c-hpa-hot"] if r["source_ip"]==ip)[pod]]
                    for ip,pod in sorted(anchor.items())]
    c_plain_counts = Counter(r["pod"] for r in by_phase["c-hpa"] if r["sent_wall_ns"]/1e9>=new_ready)
    c_cpu_peak = max(m["resource"]["current"].get("averageUtilization",0)
                     for t in c_timeline for m in t["hpa"].get("currentMetrics",[]))
    alerts = lines("alert-states.jsonl")
    alert_rows = []
    for name in ("FirstChunkSlow","RequestFailures"):
        previous = None
        for record in alerts:
            enabled = next((a["state"] for a in record["alerts"] if a["labels"]["alertname"]==name),"inactive")
            if previous != enabled:
                alert_rows.append([name, enabled, utc(record["ts"]),f'{record["ts"]-start:+.1f}'])
                previous = enabled
    proof_checks = (RESULTS/"checks.log").read_text() if (RESULTS/"checks.log").exists() else ""
    lab_footprint = (RESULTS/"footprint.txt").read_text()
    footprint = {path:size for size,path in re.findall(r"^(\S+)\s+(/var/\S+)$",lab_footprint,re.MULTILINE)}
    checks = re.search(r"Ran (\d+) tests?",proof_checks)
    summaries = {name:stats[name] for name in ["a-early","a-fixed","a-rollout-normal","a-rollback","a-kill-stream","c-hpa","c-hpa-hot",*phase_order()]}
    summaries["rollout_drains_with_running"] = len(active_drains)
    summaries["warmup_seconds"] = warm_times
    summaries["pod_witness"] = witness[:10]
    summaries["scaling"] = {"new_pod":new_pod["name"],"pod_after":new_t-start,
                            "ready_after":new_ready-start,"ready_since_born":new_ready-new_t,
                            "scale_down_delay":lowered-hot_end,"two_ready_delay":two-hot_end,
                            "affinity_distribution":dict(c_hot_counts),"cpu_peak_pct":c_cpu_peak}
    summaries["alerts"] = alert_rows
    summaries["histograms"] = b_stats
    (RESULTS/"summary.json").write_text(json.dumps(summaries,ensure_ascii=False,indent=2)+"\n")
    a_display = {"a-early":"Дефектный прогрев", "a-fixed":"Исправленный прогрев",
                 "a-rollout-normal":"Полный штатный A → B","a-bad":"Невалидная B",
                 "a-rollback":"Ответы после отката","a-kill-stream":"Принудительно остановленный поток",
                 "a-kill":"Фоновый Service во время отказа"}
    rollback_fix = ""
    if (RESULTS/"initial-helm-rollback/helm-history.json").exists():
        rollback_fix = """<p>Первый откат прервался на ConfigMap: версия A физически осталась в namespace по аннотации keep, но исчезла из активного манифеста Helm. Helm 3.17.3 не смог сопоставить её с предыдущим ресурсом релиза. В окончательном чарте обе immutable ConfigMap объявлены в каждой ревизии, а Deployment выбирает нужный mount и SHA. После этого опыт неготовой B и откат проведены повторно. Параметры Service, probes, CPU-имитатора и rollout остались прежними. <a href="results/initial-helm-rollback/helm-history.json">Первоначальная ошибка в истории Helm</a>.</p>"""
    section_a = f"""
<section id="release"><h2>A. Прогрев, rollout и откат</h2>
<p><strong>Гипотеза.</strong> Проверка HTTP в роли readiness допускает прогревающийся процесс в EndpointSlice. При завершении старого Pod активный поток должен пережить штатное обновление благодаря запасу по длительности.</p>
<p>Два прогона по 96 запросов, 3 запросов/с, одинаковые реплики, расписание, A и 20 секунд прогрева. В дефектной ревизии оба probe используют <code>/health</code>. Клиент дождался ответа от непрогретого backend в <strong>{a_early["confirmed_unwarmed"]}</strong> случаях. В исправленной оба probe используют <code>/ready</code>; подтверждённых запросов до прогрева <strong>{a_fixed["confirmed_unwarmed"]}</strong>. Liveness продолжает проверять <code>/health</code>. Startup откладывает остальные проверки и допускает до 50 проверок раз в секунду. Readiness обратимо закрывает приём через Service во время drain. Поле <code>warmed</code> замеряется на входе запроса.</p>
{figure("01-warmup-rollout","Нулевой момент — начало upgrade. EndpointSlice и Ready снимались примерно раз в секунду. Точки в первом ряду показывают подтверждённые запросы до прогрева. Короткие расхождения линий отражают разные контроллеры и дискретность съёма.")}
<p>Штатный выпуск B проверен с фоновым профилем 0,5 запроса/с в течение 55 с и тремя длинными потоками. Он использует <code>maxSurge: 1</code>, <code>maxUnavailable: 0</code>, <code>minReadySeconds: 2</code>. Первый длинный поток A начался за {(upgrade-crossing["first_ns"]/1e9-(crossing["sent_wall_ns"]-crossing["sent_ns"])/1e9):.2f} с до команды и завершился через {crossing["ended_wall_ns"]/1e9-upgrade:.2f} с после неё. Ещё два потока запущены на старых репликах непосредственно по Pod IP. Журналы зафиксировали <strong>{len(active_drains)}</strong> входов в drain с активным запросом. Hook выключает readiness и даёт 3 секунды на распространение EndpointSlice. Uvicorn завершает активные запросы в пределах следующих 25 секунд, при общем grace period 35 секунд.</p>
{table(["Pod B","Появление, с","Ready, с","От создания до Ready, с"],sorted(warm_times))}
{rollback_fix}
<p>После возврата к исправленной A новая B получила намеренно неверный ожидаемый SHA-256. В журнале она зафиксировала <code>artifact SHA-256 mismatch</code>. У неё отсутствовал Ready endpoint, все {stats["a-bad"]["sent"]} попыток шли на A. <code>helm rollback</code> к ревизии {event("a-bad","rollback")["revision"]} восстановил конфигурацию A. Клиент подтвердил версию и SHA-256 <code>{version_a}</code>. Фактический SHA-256 B в штатном выпуске <code>{version_b}</code>.</p>
<p>Для принудительного отказа после первого фрагмента запустили <code>crictl stop --timeout 0</code> внутри узла kind. Клиент успел получить HTTP {cut["status"]} и {cut["chunks"]}/{cut["payload"]["chunks"]} частей, финального маркера нет. Первый замер NotReady через {not_ready-killed:.1f} с, повторный Ready того же Pod с увеличенным restartCount через {recovered-killed:.1f} с. Попытки через Service продолжают идти по живым endpoints, клиентских повторов нет. Затем удалили Pod и дождались новой реплики. Контрольный диалог вернулся с {before["pod"]} на {after[0]["pod"]} с тем же SHA, история из запроса. Диалоги ALPHA и BETA вернули только собственные маркеры.</p>
{responses_table(stats,a_display,lambda p:a_display[p])}
<p>¹ Терминальная попытка включает ошибку, отказ, обрыв и просрочку. Полный rollout включает {stats["a-rollout-normal"]["planned"]} попыток, включая три явно выделенных длинных потока. Ноль 5xx, тайм-аутов и незавершённых потоков. HTTP 429 ({stats["a-rollout-normal"]["rejected"]}) учитывается отдельно, такой запрос отклонён до начала выдачи фрагментов. Тест на резкое завершение учитывается отдельной попыткой.</p>
<p><a href="results/timeline.jsonl">Ready и EndpointSlice</a> · <a href="results/events.jsonl">События и времена</a> · <a href="results/server/">Журнал Pod</a> · <a href="results/victim-previous.log">Журнал остановленного процесса</a></p>
</section>"""
    per_pod = [[pod,len(rs),sum(r["outcome"]=="rejected" for r in rs),ms(summarize(rs)),ms(summarize(rs),"queue")]
               for pod,rs in sorted(groups(by_phase[plotted_phase]).items())]
    idle_text = (f"В {utc(witness[0][0])} у {witness[0][1]} в очереди {witness[0][2]:.0f}, "
                 f"у {witness[0][3]} одновременно running=0 и waiting=0. Найдено {len(witness)} таких срезов." if witness
                 else "В дискретных Prometheus-срезах выбранного прогона одновременный простой второй реплики не зафиксирован.")
    b_head = ["Повтор","ClientIP TTFC p50/p95, мс (n)","Plain TTFC p50/p95, мс (n)","Ошибки, %","Cache hit среди успехов, %"]
    section_b = f"""
<section id="routing"><h2>B. Привязка и перегрузка одной реплики</h2>
<p><strong>Гипотеза.</strong> ClientIP может чаще переиспользовать локальные префиксы, но при доминирующем IP очередь этой реплики определяет TTFC. Для CPU-опыта выбран обычный ClusterIP Service с <code>sessionAffinity: None</code>. Вторая политика использует <code>ClientIP</code> с тайм-аутом 60 с над теми же Pod и selector.</p>
<p>12 прогонов. Для каждой из четырёх комбинаций три повтора по 120 с, 600 строк, по 5 запросов/с. Равномерное распределение по 150, горячий профиль 480/40/40/40. Четыре клиентских Pod в одной сети kind, kube-proxy в режиме iptables. Conntrack распределяет новые TCP-соединения. Клиент задаёт <code>Connection: close</code>, HTTP keep-alive и повторы отключены. IP у Pod совпадает с <code>client_ip</code> сервера. Пары отличаются hostname; содержимое payload, длины и запланированные времена совпадают. К началу каждого опыта оба Pod Ready, кеши очищены независимо через localhost. Средний повтор меняет порядок политик. Активные записи ClientIP живут до 60 с без обращений. В смежных прогонах через ClientIP записи могли сохраниться, это видно по трассам IP → Pod.</p>
<p>Один активный запрос и три места ожидания на Pod. LRU хранит 8 префиксов, общий набор из четырёх популярных ключей и новый холодный ключ в каждой 13-й позиции. Цена hit/miss 180/440 мс, после первой части две очередные части каждые 60 мс, CPU burn выключен. При полном буфере HTTP 429 возвращается сразу. Максимальная задержка запуска клиента относительно плана за 12 прогонов {max(stats[p]["peak_send_lag_ms"] for p in phase_order()):.1f} мс. Запланированные и фактические времена приложены.</p>
{figure("02-per-pod",f"Опыт {plotted_phase}. TTFC измерен на клиенте, ожидание очереди передано сервером в первом фрагменте.")}
{table(["Pod","Все попытки","429","TTFC p50/p95, мс (n)","Очередь p50/p95, мс (n)"],per_pod)}
<p>{idle_text} При сравнении полезен и случай без явного перекоса: в <code>{balanced}</code> трасса распределила запросы {', '.join(f'{pod}: {count}' for pod,count in balanced_counts)}. В обычном Service новые соединения могут менять Pod даже от того же IP. В ClientIP распределение определяется тем, куда попали конкретные IP; четыре клиента сами по себе гарантий 50/50 не дают.</p>
{figure("03-routing-comparison","Результаты всех трёх повторов по каждой политике. p95 рассчитана по успешным ответам. Доля ошибок включает отказанные запросы.")}
<p><strong>Горячий профиль, переход ClientIP → обычный Service.</strong></p>
{table(b_head,hot_conclusion)}
<p>Переключение на обычный Service распределяет запросы от горячего IP между двумя очередями. Цена решения — отсутствует явная маршрутизация по префиксу. Общий рабочий набор помещается в оба локальных кеша имитатора. На inference engine нужно отдельно измерить выигрыш KV-кеша, prefill для разных длин, очереди continuous batching, скорость выдачи токенов, использование памяти и простои при горячем контексте.</p>
{responses_table(stats,phase_order(),lambda p:p)}
<details><summary>Трасса IP → Pod по всем двенадцати прогонам</summary>{table(["Прогон","IP источника","Распределение попыток"],ranges)}</details>
<p><a href="results/client-pods.json">4 IP Pod</a> · <a href="results/routing-services.json">Два Service</a> · <a href="results/network.txt">kube-proxy</a> · <a href="results/routing-monitoring.json">Показания running/waiting с обоих Pod</a></p>
</section>"""
    cmp_rows = []
    for phase,x in b_stats.items():
        empirical = stats[phase]["ttfc"]["p95"]
        cmp_rows.append([phase,stats[phase]["ok"],x["count"],f"{empirical*1000:.1f}",
                         f'{x["bucket_p95"]*1000:.1f}',f'{x["range_p95"]*1000:.1f}'])
    sample_promql = b_stats["b-hot-plain-1"]["expression"]
    section_c = f"""
<section id="scale"><h2>C. HPA и алерты</h2>
<p><strong>Гипотеза.</strong> HPA реагирует на CPU, но маршрутизация ClientIP сохраняет горячую очередь и после масштабирования. У каждого контейнера API есть <code>requests.cpu=100m</code>. <code>autoscaling/v2</code> держит диапазон 2–3 и средний target 55%. Ресурсные метрики получены через <code>metrics.k8s.io/v1beta1</code>; источник — Metrics Server.</p>
<p>До увеличения нагрузки каждый из четырёх IP получил привязку к одному из исходных Pod через ClientIP. Во время опыта поддерживали эти привязки с частотой 0,5 запроса/с суммарно. На обычный Service подали 12 запросов/с на 86 секунд, с 130 мс работы CPU на принятый запрос и интервалом частей 120 мс. Пиковая измеренная HPA загрузка {c_cpu_peak}% от requests. Третий Pod увидели через {new_t-start:.1f} с от начала основного опыта, Ready через {new_ready-start:.1f} с. Разница {new_ready-new_t:.1f} с включает запуск и прогрев. После Ready обычный Service распределил попытки так: {dict(c_plain_counts)}.</p>
{figure("04-hpa","Поступление нагрузки, средний CPU HPA, количество созданных и Ready Pod. Основной CPU-трафик сменяется 30-секундным профилем ClientIP.")}
<p>Следом подали 10 запросов/с на ClientIP, 80% от client-0, в течение 30 с начиная с +{hot_start-start:.1f} с. Попытки по Pod: {dict(c_hot_counts)}. Третий Pod получил {c_hot_counts[new_pod["name"]]} из 300 попыток. Горячий клиент переиспользует привязку 60 с; новая реплика получает только выбранные для неё IP. При одинаковых CPU requests среднее двух Pod приблизительно (u₁ + u₂) / 2. Один горячий Pod при почти нулевой загрузке второго должен устойчиво превышать примерно 110% CPU request, плюс запас на допуск контроллера и дискретность. Очередь при I/O-ожидании CPU почти не нагружает. Поэтому CPU HPA дополняет маршрутизацию, а для настоящего inference важны также очередь и доступные ресурсы ускорителя.</p>
{table(["IP клиента","Исходный Pod ClientIP","Попытки на исходном Pod после scale-up"],anchor_trace)}
<p>Downscale stabilization задан 45 с. После последней фазы нагрузки desired стал 2 через {lowered-hot_end:.1f} с, а оба Pod Ready и лишний исчез через {two-hot_end:.1f} с. В реальное время входят окно Метрик, опрос HPA, preStop и завершение Pod.</p>
{responses_table(stats,["c-hpa","c-hpa-hot"],lambda p:p)}
<h3>Два алерта</h3>
<p>Окно 24 с, evaluation interval 3 с, удержание 12 с. <code>FirstChunkSlow</code> требует TTFC p95 &gt;850 мс при ≥20 успешных. <code>RequestFailures</code> требует &gt;10% отказов и ошибок при ≥20 терминальных исходах. Prometheus скрейпит каждый Pod напрямую через discovery, включая фазу прогрева. Состояния <code>pending</code>, <code>firing</code> и отсутствие после спада получены через <code>/api/v1/alerts</code>.</p>
{table(["Алерт","Состояние","Время","Секунды от нагрузки"],alert_rows)}
<p><a href="results/hpa.yaml">HPA и CPU target</a> · <a href="results/resource-metrics-start.json">Resource Metrics API</a> · <a href="results/hpa-monitoring.json">CPU, RSS, running/waiting и алерты</a> · <a href="monitoring/dashboard.json">Экспорт Grafana</a></p>
</section>"""
    measurement = f"""
<section id="measure"><h2>Как считались задержки</h2>
<p>Клиенты фиксируют <code>scheduled_ns</code>, <code>sent_ns</code>, <code>first_ns</code>, <code>ended_ns</code> на монотонных часах, ns. Отправка отмечается непосредственно перед HTTP-вызовом и включает открытие TCP-соединения. Общий эпохальный якорь синхронизирует отправку из четырёх Pod одного узла. TTFC = первый содержательный NDJSON-фрагмент − отправка. Inter-chunk latency — последовательные разности между содержательными частями. Время полного ответа — до закрытия HTTP-тела. Успех требует ожидаемого числа частей и маркера <code>done</code>. Для каждого запроса сохраняются payload, ID, IP, Pod, версия, SHA, warmed, статус, исход, очередь и интервалы. Разовый сокетный timeout 16 с применяется к отдельной операции чтения.</p>
<p>Для реальной модели TTFT определялся бы от отправки до прихода первого содержательного токена, TPOT = (t последнего токена − t первого) / (N−1). N — число фактически выданных токенов по token IDs сервера, без токенов запроса и служебных маркеров. Для N=1 TPOT отсутствует. Tokens/s для участка decode = (N−1)/(t последнего − t первого). Здесь измерялись только части имитатора.</p>
<p>Сервер наблюдает histogram для успешных TTFC, полного ответа и ожидания, bucket-границы от 0,01 до 25 с. Источник интервалов в отдельной histogram — все выданные фрагменты. Пример PromQL для интервала одного полного прогона B с запасом на последнее чтение:</p>
<pre>{html.escape(sample_promql)}</pre>
<p>Используется сумма по <code>le</code> двух Pod, для разреза сохраняется <code>(le,pod)</code>. Для сверки за тот же набор запросов вычислили точную разность bucket-счётчиков на срезах до/после. Между срезами работает только один генератор. Количество по <code>+Inf</code> сверено с клиентским числом успехов. P95 из bucket интерполируется внутри интервала; клиентский p95 вычислен из времён успешных попыток, с линейной интерполяцией между соседними наблюдениями. Разницу дают границы bucket, путь HTTP и экстраполяция <code>increase()</code> по дискретным scrape-точкам.</p>
{table(["Прогон","Клиент n","Histogram n","Клиент p95, мс","Bucket delta p95, мс","PromQL p95, мс"],cmp_rows)}
<p>Дашборд показывает TTFC, полное время, inter-chunk, текущие running/waiting, завершённые запросы, ошибки и отказы, CPU и RSS Python-процессов и число Ready по kube-state-metrics. CPU контейнера для HPA взят из resource metrics, отдельно от CPU процесса. Метки метрик ограничены именем Pod и конечными наборами исходов/результатов кеша. Request ID и session ID остаются в журнале. Принудительное убийство может завершить процесс до отправки финальной метрики, поэтому обрыв подтверждает клиент.</p>
<p><a href="results/requests.jsonl">Запросы JSONL</a> · <a href="results/prometheus-targets.json">Цели Prometheus</a> · <a href="https://prometheus.io/docs/practices/histograms/">Histogram в документации Prometheus</a></p>
</section>"""
    review = f"""
<section id="review"><h2>Ревью PR · привязка диалога к Pod</h2>
<p>При исходных оценках новый запрос отправил бы на B. Доплата за холодный prefill 0,8 с меньше 3 с очереди A. Проверяю лимиты B по активным запросам и KV-памяти, его Ready, допустимую версию и предсказанный TTFT c deadline. Сравниваю прогноз CPU/GPU и очередь в секундах, длину входа и ожидаемый cache hit на каждом Pod. Счётчик ожидающих без размеров prefill и decode плохо предсказывает время ожидания. Нужны p95 TTFT с разбивкой по длине, погрешность прогноза, доля попаданий, насыщение и отказы. При равном прогнозе отдаю предпочтение кешу. При исчерпании бюджета времени или очереди возвращаю ограниченный отказ с явной политикой повтора.</p>
<p>Историю и идентификатор диалога клиент присылает вместе с запросом либо читает из стойкого общего хранилища. После потери A готовая совместимая реплика пересчитывает контекст по этому источнику. Уже начатый поток закреплён за тем соединением и версией, где начался. При штатном rollout его обслуживает прежняя реплика до конца. При падении фиксирую частичный результат и отдельный повтор с тем же логическим ID и новым ID попытки. Клиент решает, заменить ли частичный вывод. Для инструментальных вызовов отдельно нужны идемпотентные ключи, чтобы не выполнить побочный эффект дважды.</p>
<p>Кейс Google из слайда 070. GKE Inference Gateway учитывает очереди и локальность префикса. Google сообщает о росте cache hit с 35% до 70% и снижении p95 TTFT на 52% для DeepSeek V3.1 на всплесках чатов. Здесь у выбора похожий критерий, а числа получены только на лабораторной модели нагрузки. <a href="https://cloud.google.com/blog/products/containers-kubernetes/how-gke-inference-gateway-improved-latency-for-vertex-ai">Первичный источник Google Cloud</a>.</p>
<p>Ещё один цикл на настоящем inference engine должен включить неравные длины prefill, реальные токены decode, отличающиеся размеры KV, истечение cache hit и отказ во время потока. CPU-имитатор покрывает проверяемость маршрутизации, Kubernetes и измерений. Один узел ограничивает интерпретацию сетевых и отказных эффектов. Клиенты открывают новые соединения, поэтому баланс для длинных keep-alive и HTTP/2 нужно измерить отдельно.</p>
</section>"""
    percent = lambda p: statistics.median(stats[n]["errors_pct"] for n in phase_order() if f"-hot-{p}-" in n)
    top = f"""
<header><p>МГТУ им. Н. Э. Баумана · MLOps-26</p><h1>ДЗ11. Kubernetes под нагрузкой</h1>
<p>Две реплики FastAPI на kind, CPU backend <code>simulated</code>, три воспроизводимых опыта. Продолжение сервиса из ДЗ8–10.</p>
<nav><a href="#lab">Стенд</a><a href="#release">Прогрев и rollout</a><a href="#routing">Маршрутизация</a><a href="#scale">HPA</a><a href="#measure">Метрики</a><a href="#review">Ревью</a></nav></header>
<aside class="facts"><span><strong>{stats["a-rollout-normal"]["ok"]}/{stats["a-rollout-normal"]["planned"]}</strong> успешных в штатном A → B</span><span><strong>{percent("affinity"):.1f}% → {percent("plain"):.1f}%</strong> медиана ошибок на горячем профиле</span><span><strong>2 → 3 → 2</strong> масштабирование по CPU</span></aside>
<section id="lab"><h2>Стенд</h2>
<p>macOS arm64, Colima/VZ, Docker Server 29.5.2, kind 0.27.0, Kubernetes 1.32.2, Helm 3.17.3. Перед запуском на диске было 322 GiB свободно. Контейнерная VM получила 4 vCPU и 5 GiB RAM. В отдельном профиле настроен диск 20 GiB.</p>
<p>Две рабочие реплики, лимиты каждого Pod API 500m CPU и 192 MiB RAM, requests 100m и 80 MiB. Встроенный файл A/B лежит в immutable ConfigMap, имя включает префикс SHA. Содержимое проверяется до прогрева. Код и хеши зависимостей поставляются с Dockerfile. Артефакт восстанавливается из ConfigMap при каждом старте. Для настоящих весов вариант доставки — версионированный ключ в объектном хранилище и подписанный манифест с SHA. Каждая реплика может получить тот же артефакт в собственный ограниченный том. Размещение на разных узлах не зависит от совместного подключения RWO. Проверка контрольной суммы и прогрев остаются условиями Ready.</p>
<p>Фактические размеры стенда после экспериментов: база контейнеров на узле {footprint.get("/var/lib/containerd","—")}, kubelet {footprint.get("/var/lib/kubelet","—")}, etcd {footprint.get("/var/lib/etcd","—")}, журналы Pod {footprint.get("/var/log/pods","—")}. Инвентарь содержит размер Docker-образов и их идентификаторы. Размер образов в Docker image inspect и распакованные snapshot в containerd учитываются раздельно. Prometheus хранит до 6 ч / 96 MB TSDB-блоков, volume ограничен 256 MiB. Grafana хранит данные в emptyDir 96 MiB. Поставлены Prometheus 3.3.1, Grafana 11.6.1, kube-state-metrics 2.15.0, Metrics Server 0.8.0.</p>
<p><code>./lab.sh up</code> разворачивает стенд, <code>./lab.sh down</code> удаляет только кластер <code>hw11</code> и его локальный образ. Удаление отдельной VM по команде <code>colima delete hw11</code>. <a href="README.md">Инструкция</a> · <a href="results/environment.txt">Окружение до запуска</a> · <a href="results/footprint.txt">Размеры</a> · <a href="results/images.json">Дайджесты образов на узле</a>.</p>
<p>{checks.group(1) if checks else "—"} проверок сохранено в <a href="results/checks.log">журнале</a>. Первые три утверждения проверяют ответы реальных HTTP-вызовов из Kubernetes: доступ во время прогрева, версию после отката и замену Pod. Ещё два утверждения проверяют отказ и обрыв, затем изоляцию диалогов на одной новой реплике. Live smoke обращается к ClusterIP с четырёх IP.</p>
</section>"""
    style = """
:root{--ink:#182844;--muted:#405271;--accent:#174893;--border:#c9d6e7;--paper:#fff}
*{box-sizing:border-box} body{margin:0;background:#eff4fa;color:var(--ink);font:16px/1.57 system-ui,sans-serif}
main{max-width:1260px;margin:0 auto;padding:35px clamp(16px,4vw,50px) 60px} header{border-bottom:1px solid var(--border);padding-bottom:22px}
h1{font-size:clamp(2rem,5vw,3.1rem);line-height:1.12;margin:.2em 0} h2{font-size:1.7rem;line-height:1.2;margin:0 0 1rem} h3{margin-top:1.5rem}
header p,figcaption{color:var(--muted)} a{color:var(--accent)} nav,.facts{display:flex;gap:1em 2em;flex-wrap:wrap}
.facts{margin:20px 0 28px;border-bottom:1px solid var(--border);padding-bottom:18px}
.facts span{min-width:230px}.facts strong{display:block;color:var(--accent);font-size:1.6rem}
section{margin:22px 0;padding:clamp(14px,3vw,30px);background:var(--paper);border:1px solid var(--border);border-radius:8px}
figure{margin:1.4em 0} img{max-width:100%;height:auto} figcaption{font-size:.9rem} code,pre{background:#eaf1fa;border-radius:3px;overflow-wrap:anywhere}
code{padding:.1em .25em} pre{padding:12px;overflow:auto} .table{overflow:auto;margin:1.1em 0}
table{width:100%;border-collapse:collapse;font-size:.85rem;line-height:1.4} td,th{text-align:left;padding:8px 9px;border:1px solid var(--border)}
th{background:#ebf2fb} tr:nth-child(even){background:#f7f9fc} summary{cursor:pointer;color:var(--accent)} @media print{body{background:white} section{break-inside:auto} nav{display:none}}
"""
    doc = f'<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>ДЗ11 · Kubernetes под нагрузкой</title><style>{style}</style><main>{top}{section_a}{section_b}{section_c}{measurement}{review}</main></html>'
    (ROOT/"report.html").write_text(doc+"\n")


def main():
    by_phase=defaultdict(list)
    for row in lines("requests.jsonl"):
        by_phase[row["phase"]].append(row)
    by_phase["a-rollout-normal"]=[r for p,rs in by_phase.items()
                                  if p.startswith("a-rollout") for r in rs]
    stats={p:summarize(rs) for p,rs in by_phase.items()}
    timeline,events=lines("timeline.jsonl"),lines("events.jsonl")
    plot_a(by_phase,timeline,events)
    plotted_phase=plot_b_pods(by_phase,stats)
    plot_b_runs(stats)
    plot_c(by_phase,timeline,events)
    report(by_phase,stats,timeline,events,plotted_phase)


if __name__ == "__main__":
    main()
