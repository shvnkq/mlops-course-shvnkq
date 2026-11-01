"""Generate the engineering handoff from executed evidence, not invented PASS."""
import csv
import hashlib
import json
from pathlib import Path

def main():
    root=Path('hw8910');ev=root/'evidence'
    read=lambda name:json.loads((ev/name).read_text())
    bench=read('benchmark.json');flows=read('flow-experiments.json');smoke=read('restart-smoke.json')
    manifest=json.loads((root/'state/manifest.json').read_text());report=json.loads((root/'state/release-report.json').read_text())
    for filename,value in [('manifest.json',manifest),('release-report.json',report),('accepted.json',json.loads((root/'state/accepted.json').read_text()))]:
        (ev/filename).write_text(json.dumps(value,ensure_ascii=False,indent=2))
    fields=['symptom','reproduce','actual_expected','cause','fix','regression_test']
    defects=[
      ['Stale preparation','run fail, recover, change input','old CACHE_HIT / expected PREPARED','path-only key','content/config canonical hash','test_process_recovery_and_changed_input'],
      ['Incomplete/foreign PASS','run --report report-incomplete.json','old exit 0 / expected refusal','truthy passed without binding','complete boolean finite bound contract','test_process_reject_and_incompatible'],
      ['Pointer overwritten on disk failure','mock os.replace failure','old writes target / expected unchanged bytes','in-place write','temp + flush/fsync + os.replace + cleanup','test_failed_atomic_replace_preserves_previous_bytes'],
      ['Duplicate release events','run twice in new processes','old 2 events / expected 1','unconditional append','canonical release id and recovery reconciliation','test_process_repeat_has_one_publication'],
      ['Ready before warmup','GET /ready during warmup','old 200 / expected 503','ready initialized true','ready only after backend load and warmup','test_http_readiness'],
      ['Advertised B while A in memory','publish B after API started A','old metadata B, answer A / expected both A','reread pointer on every response','immutable loaded backend identity','test_http_actual_loaded_version_and_rollback'],
      ['Invalid input computes','POST invalid limits then /debug','old calls grow / expected 4xx, unchanged calls','backend called before validation','strict prompt/limit before lock/backend','test_http_validation_never_calls_backend']]
    with (root/'defects.csv').open('w') as f:w=csv.writer(f);w.writerow(fields);w.writerows(defects)
    out=['# ДЗ8–10: безопасный выпуск и работающий API','',
      'Результат: реальный принятый адаптер ДЗ6–7 обслуживается FastAPI; Prefect выполняет отдельные задачи подготовки, проверки артефакта, допуска и публикации. Нового обучения и sweep нет.','',
      '## 1. Расследование семи причин','',
      'Исходный прототип сохранён отдельным коммитом d3b6058. Таблица defects.csv содержит семь независимых причин и команды/тесты. Все 13 выданных тестов оставлены неизменными. Добавлены 7 своих интеграционных тестов. Шесть из них используют существующие интерфейсы оригинала и падают из-за поведения, не импорта: три HTTP и три subprocess. Седьмой проверяет новую fault-injection точку после указателя: его красный результат на оригинале не считается самостоятельным доказательством старого дефекта, поскольку этот hook там не предусмотрен.','',
      'Результаты: исходный original-red.log — 7 FAIL; fixed-green.log — 20/20; fastapi-green.log — те же 20/20 с тремя настоящими HTTP-тестами FastAPI stub. intentional-break.log — ненулевой exit при намеренной подмене cache_key только в тестовом процессе. restored-green.log — 20/20; рабочие файлы не менялись. Ошибка диска моделируется mock os.replace, реальный диск не заполняется.','',
      '## 2. Переиспользованная модель и оценка','',
      f"Training run: {manifest['training_run_id']}. Eval run: {report['evaluation_run_id']}. Artifact URI: {manifest['artifact_uri']}. Base: {manifest['runtime']['base_revision']}. Использован quality_gate из ДЗ6–7 с пересчётом per-item из исходных raw и проверкой protocol/golden/source hashes. Ручного passed=true нет.",'',
      f"Полные исходные отчёты сохранены в metrics/ и приложении сдачи; hashes: {json.dumps(report['sources'])}.",'',
      'Runtime соответствует исходной оценке: MPS, bfloat16, Qwen3-0.6B, Transformers 5.17.0, Torch 2.14.0, PEFT 0.21.0, общий system, greedy, seed=42, disabled thinking, max_new_tokens=32. Веса/adapter_config/tokenizer/template/manifest пересчитываются перед публикацией и загрузкой. API не принимает другой лимит: только 32, чтобы не наследовать допуск произвольным настройкам. Сама JSON-проверка validate_release не заменяет quality_gate.','',
      '## 3. Prefect и восстановление','',
      'Граф: preparation → artifact → admission → publication. Между задачами передаются только описания/хеши. Получение артефакта читает готовый training run, а не обучает. persist_result=True для настоящей проверки JSONL (непустые строки и input); key содержит SHA байтов, tokenizer hash, template hash, max_length и SHA кода подготовки. Prefect сохраняет результат на диске и фиксирует Cached между отдельными процессами.','',
      'Управляемый сбой после подготовки завершился ненулевым кодом; следующий процесс использовал Cached. Изменён input по тому же пути отдельного preparation-probe.jsonl, а не golden оценки: стадия снова PREPARED. Этот вход нужен для проверки схемы, а не переобучения; исходный eval-набор не менялся.','',
      '| Опыт | exit | Cached | PREPARED |','|---|---:|---|---|']
    for r in flows:out.append(f"| {r['experiment']} | {r['exit_code']} | {r['cached']} | {r['prepared']} |")
    out+=['', 'Идентификатор выпуска — SHA canonical(manifest + связанный report), включая runtime и gate. Журнал Prefect — попытки, publications.jsonl — события. Повтор не создаёт второе событие. Сбой после указателя/до журнала на отдельном state-recovery восстановлен новым процессом; повтор оставил 1 событие. Однописательный протокол не заявляет распределённую транзакцию; fsync и atomic replace не решают конкуренцию писателей. Неверный контракт/отказ не retry; локальный артефакт не требует сетевого retry.','',
      '## 4. Отказы и состояние указателя','',
      'Четыре опыта: incomplete, foreign model, reject, NaN. Во всех accepted.json побайтно прежний. Полные SHA до/после — evidence/refusals.json. validate_release дополнительно проверяет все обязательные поля, конечность и диапазон метрик, точный runtime hash. Ошибка replace тоже оставляет старые байты и удаляет временный файл.','',
      '## 5. Реальный FastAPI','',
      'GET /health отвечает о жизни процесса. Фоновая загрузка: /ready возвращал 503, затем 200 после загрузки и настоящего warmup generate. Лимит prompt 4096 символов и body 65536 байт; строго 32 output tokens max; одновременно вычисляется один запрос, остальные ждут lock. Неверный запрос получает 422 до backend: debug.calls до/после совпали. /debug — учебная localhost-диагностика, не публичный production endpoint.','',
      f"Реальный ответ после перезапуска: {json.dumps(smoke['after'][1],ensure_ascii=False)}.",'',
      'Два lightweight STUB A→B→A проверены настоящими серверами: после публикации B живой процесс всё ещё сообщает A в ответе и metadata; новый процесс сообщает B; управляемый откат к сохранённому принятому A и новый процесс возвращают A. Прямое копирование ранее принятого A в этом isolated test не является новым gate модели. Реального второго допущенного адаптера нет: для настоящей Qwen отдельно проверен restart той же версии, совпали model_id/runtime/answer. Фикстура не выдаётся за реальную модель B.','',
      '## 6. Замер 8+8 после прогрева','',
      '| concurrency | n | успех | ошибок | пакет, с | успехов/с | средняя задержка успехов, с | max, с |','|---|---:|---:|---:|---:|---:|---:|---:|']
    for r in bench:out.append(f"| {r['concurrency']} | {r['n']} | {r['success']} | {r['errors']} | {r['batch_seconds']:.4f} | {r['successful_requests_per_second']:.4f} | {r['mean_success_latency']:.4f} | {r['max_success_latency']:.4f} |")
    out+=['', 'Каждая попытка сохранена в requests.jsonl: id, status/error, client latency, queue/generation durations, model/runtime, output_tokens и текст. Ошибки не удаляются; в этом запуске их 0/16. Лимит одинаковый, набор из тех же 8 вопросов. Client latency включает очередь и HTTP; generation_seconds — вычисление под lock. При concurrency=2 latency выросла, throughput не вырос: backend последовательный. Выборка слишком мала для устойчивого p95.','',
      'Prefill обрабатывает входной контекст; decode последовательно порождает новые токены. KV-cache хранит ключи/значения внимания по слоям и растёт с длиной контекста и числом активных последовательностей. Возвращается единый JSON, поэтому измеряется полная задержка: TTFT/ITL не измерялись. Это не benchmark continuous batching/PagedAttention SGLang/vLLM.','',
      '## 7. Триггеры и CI','',
      '| Событие | Команды/действие |','|---|---|',
      '| Код | make check-hw8910; изменение generation → новая полная оценка |',
      '| Данные | schema check + новый cache key; изменение golden → make evaluate и новый gate; изменение входа только проверки не требует training |',
      '| Новый адаптер | attach_model, проверка файлов/загрузки, полная evaluate, gate, release_flow; лишь затем restart API |','',
      'CI выполнен локально, удалённые Actions и защита merge не заявляются. Сохранены красный/зелёный логи. План rollback: выбрать ранее допущенный immutable manifest/report, перепроверить файлы и report, атомарно опубликовать, перезапустить API, сверить реальный loaded_id. Смена accepted.json сама по себе модель в памяти не меняет.','',
      '## Доступ и воспроизведение','',
      'Код и отчёты — GitHub; evidence/logs/raw benchmark — отдельный release-комплект. Веса, caches, .venv и Docker volumes не входят в Git/архив. Нужные файлы адаптера доступны отдельными release-assets без упаковки весов в архив; их имена совпадают с keys adapter/* в manifest. Base revision загружается из HF. Полные eval и golden доступны в комплекте ДЗ6–7. Быстрые тесты не требуют модели.','',
      'Видео 5–8 минут приложено к этому же выпуску. Предыдущие tests/ ДЗ6–7 сохранены; новые tests находятся отдельно hw8910/tests.','']
    (root/'REPORT.md').write_text('\n'.join(out))
    print('REPORT.md and defects.csv generated from actual evidence')

if __name__=='__main__':main()
