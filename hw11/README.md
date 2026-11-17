# ДЗ11 · Kubernetes под нагрузкой

Продолжение FastAPI-сервиса из [ДЗ8–10](../hw8910/REPORT.md). Сохранены `/health`, `/ready`, `POST /generate`, вход `prompt` + `max_new_tokens=32`, идентификаторы запроса и артефакта. Для Kubernetes добавлены NDJSON-поток, клиентская история, ограниченная очередь, локальный префиксный LRU и CPU-имитатор с `backend_mode=simulated`. Версия A/B обозначает файл из чарта. Обе immutable ConfigMap входят в каждую ревизию Helm. SHA-256 выбранной версии проверяется при старте каждого Pod.

- [Отчёт HTML](report.html) и [четыре графика](figures/)
- [Сырые запросы](results/requests.jsonl), [Ready и EndpointSlice](results/timeline.jsonl), [события](results/events.jsonl)
- [Helm](chart/), [материалы мониторинга](monitoring/), [Dockerfile](Dockerfile) и [проверки](check.py)

## Запуск

Нужны Docker, Bash, Python ≥3.9, kind 0.27.0, kubectl 1.32.2, Helm 3.17.3. Использовался отдельный профиль Colima на macOS arm64. На Docker Desktop используйте свой текущий контекст Docker.

```bash
cd hw11
# Только если используете Colima
colima start hw11 --cpu 4 --memory 5 --disk 20 --vm-type vz
export DOCKER_CONTEXT=colima-hw11

# Повтор сохраняет новые измерения в отдельную директорию
export HW11_RESULTS="$PWD/replay-results"
./lab.sh up
export KUBECONFIG="$PWD/.kubeconfig"
kubectl --context kind-hw11 -n hw11 get pods -o wide
kubectl --context kind-hw11 -n hw11 top pods
```

У lab отдельный kubeconfig. Grafana и Prometheus доступны через localhost в отдельных терминалах.

```bash
kubectl --context kind-hw11 -n hw11 port-forward svc/grafana 13000:3000
kubectl --context kind-hw11 -n hw11 port-forward svc/prometheus 19090:9090
```

Grafana: `http://127.0.0.1:13000/d/hw11`. Prometheus: `http://127.0.0.1:19090/targets`. Grafana включена в режиме Viewer для локального стенда. Metrics Server использует `--kubelet-insecure-tls` для локальных сертификатов kind.

## Замеры и самопроверка

```bash
python3 experiments.py a b c
python3 snapshot_metrics.py
python3 check.py --live
./lab.sh inventory
```

Опыт B содержит 12 отдельных 120-секундных прогонов. Полный цикл занимает около получаса. Для повторного опыта используйте новый `HW11_RESULTS`. Опыт B пропускает полностью сохранённые прогоны, если продолжить запись в ту же папку. Проверьте сырые строки незавершённого прогона перед его повтором, чтобы в журнале не появились повторы идентификаторов.

Для проверки приложенных результатов достаточно `env -u HW11_RESULTS python3 check.py`. Для перестроения графиков и отчёта из них используйте `uv run --no-project --with matplotlib==3.10.8 python analyze.py`. Флаг `--live` обращается к Kubernetes и дописывает четыре попытки smoke в выбранную папку результатов.

## Удаление

```bash
./lab.sh down
# Если выделяли отдельный профиль только для ДЗ11
colima delete hw11
```
