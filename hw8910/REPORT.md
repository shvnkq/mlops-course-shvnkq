# ДЗ8–10: безопасный выпуск и работающий API

Результат: реальный принятый адаптер ДЗ6–7 обслуживается FastAPI; Prefect выполняет отдельные задачи подготовки, проверки артефакта, допуска и публикации. Нового обучения и sweep нет.

## 1. Расследование семи причин

Исходный прототип сохранён отдельным коммитом d3b6058. Таблица defects.csv содержит семь независимых причин и команды/тесты. Все 13 выданных тестов оставлены неизменными. Добавлены 7 своих интеграционных тестов. Шесть из них используют существующие интерфейсы оригинала и падают из-за поведения, не импорта: три HTTP и три subprocess. Седьмой проверяет новую fault-injection точку после указателя: его красный результат на оригинале не считается самостоятельным доказательством старого дефекта, поскольку этот hook там не предусмотрен.

Результаты: исходный original-red.log — 7 FAIL; fixed-green.log — 20/20; fastapi-green.log — те же 20/20 с тремя настоящими HTTP-тестами FastAPI stub. intentional-break.log — ненулевой exit при намеренной подмене cache_key только в тестовом процессе. restored-green.log — 20/20; рабочие файлы не менялись. Ошибка диска моделируется mock os.replace, реальный диск не заполняется.

## 2. Переиспользованная модель и оценка

Training run: dbbef824856a45c9a784bb046d21113a. Eval run: ce237897c74149238a6afd2e2789156d. Artifact URI: models:/geonames-qwen-adapter/1. Base: c1899de289a04d12100db370d81485cdf75e47ca. Использован quality_gate из ДЗ6–7 с пересчётом per-item из исходных raw и проверкой protocol/golden/source hashes. Ручного passed=true нет.

Полные исходные отчёты сохранены в metrics/ и приложении сдачи; hashes: {"metrics/baseline-eval.json": "88a407f628da45fcd3b17fdbdf0b00cbef0e9612f466275b2862d3227b3fab50", "metrics/candidate-eval.json": "bfe83da18a6086eabb35759801b054d8cc6d191f730f124b9004058d4b2ff8c0", "metrics/baseline-outputs.json": "e2cbf3caa5a6f85f00f66067d61e919dc7d6aa1ec801ba8f62b35778450f27a0", "metrics/candidate-outputs.json": "497feeace1027d215de5085482ea600c3d4535d5d3e970d091e525421606d465"}.

Runtime соответствует исходной оценке: MPS, bfloat16, Qwen3-0.6B, Transformers 5.17.0, Torch 2.14.0, PEFT 0.21.0, общий system, greedy, seed=42, disabled thinking, max_new_tokens=32. Веса/adapter_config/tokenizer/template/manifest пересчитываются перед публикацией и загрузкой. API не принимает другой лимит: только 32, чтобы не наследовать допуск произвольным настройкам. Сама JSON-проверка validate_release не заменяет quality_gate.

## 3. Prefect и восстановление

Граф: preparation → artifact → admission → publication. Между задачами передаются только описания/хеши. Получение артефакта читает готовый training run, а не обучает. persist_result=True для настоящей проверки JSONL (непустые строки и input); key содержит SHA байтов, tokenizer hash, template hash, max_length и SHA кода подготовки. Prefect сохраняет результат на диске и фиксирует Cached между отдельными процессами.

Управляемый сбой после подготовки завершился ненулевым кодом; следующий процесс использовал Cached. Изменён input по тому же пути отдельного preparation-probe.jsonl, а не golden оценки: стадия снова PREPARED. Этот вход нужен для проверки схемы, а не переобучения; исходный eval-набор не менялся.

| Опыт | exit | Cached | PREPARED |
|---|---:|---|---|
| flow-repeat | 0 | True | False |
| flow-probe-initial | 0 | True | False |
| flow-input-changed | 0 | False | True |
| flow-pointer-crash | 1 | True | False |
| flow-pointer-repair | 0 | True | False |
| flow-pointer-repeat | 0 | True | False |

Идентификатор выпуска — SHA canonical(manifest + связанный report), включая runtime и gate. Журнал Prefect — попытки, publications.jsonl — события. Повтор не создаёт второе событие. Сбой после указателя/до журнала на отдельном state-recovery восстановлен новым процессом; повтор оставил 1 событие. Однописательный протокол не заявляет распределённую транзакцию; fsync и atomic replace не решают конкуренцию писателей. Неверный контракт/отказ не retry; локальный артефакт не требует сетевого retry.

## 4. Отказы и состояние указателя

Четыре опыта: incomplete, foreign model, reject, NaN. Во всех accepted.json побайтно прежний. Полные SHA до/после — evidence/refusals.json. validate_release дополнительно проверяет все обязательные поля, конечность и диапазон метрик, точный runtime hash. Ошибка replace тоже оставляет старые байты и удаляет временный файл.

## 5. Реальный FastAPI

GET /health отвечает о жизни процесса. Фоновая загрузка: /ready возвращал 503, затем 200 после загрузки и настоящего warmup generate. Лимит prompt 4096 символов и body 65536 байт; строго 32 output tokens max; одновременно вычисляется один запрос, остальные ждут lock. Неверный запрос получает 422 до backend: debug.calls до/после совпали. /debug — учебная localhost-диагностика, не публичный production endpoint.

Реальный ответ после перезапуска: {"answer": "{\n  \"answer\": \"A\"\n}", "output_tokens": 10, "model_id": "dbbef824856a45c9a784bb046d21113a", "runtime_sha256": "45167ab6e8563be18c86539eab3c6913e83562b32555712055a5b60a13fc3819", "request_id": "183c5312-f5dc-4f72-bcf1-612e772f863a", "generation_seconds": 0.3692193330498412, "queue_seconds": 2.541986759752035e-06, "total_seconds": 0.3693039169884287}.

Два lightweight STUB A→B→A проверены настоящими серверами: после публикации B живой процесс всё ещё сообщает A в ответе и metadata; новый процесс сообщает B; управляемый откат к сохранённому принятому A и новый процесс возвращают A. Прямое копирование ранее принятого A в этом isolated test не является новым gate модели. Реального второго допущенного адаптера нет: для настоящей Qwen отдельно проверен restart той же версии, совпали model_id/runtime/answer. Фикстура не выдаётся за реальную модель B.

## 6. Замер 8+8 после прогрева

| concurrency | n | успех | ошибок | пакет, с | успехов/с | средняя задержка успехов, с | max, с |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1 | 8 | 8 | 0 | 2.8615 | 2.7958 | 0.3573 | 0.4079 |
| 2 | 8 | 8 | 0 | 3.0442 | 2.6280 | 0.7129 | 0.8360 |

Каждая попытка сохранена в requests.jsonl: id, status/error, client latency, queue/generation durations, model/runtime, output_tokens и текст. Ошибки не удаляются; в этом запуске их 0/16. Лимит одинаковый, набор из тех же 8 вопросов. Client latency включает очередь и HTTP; generation_seconds — вычисление под lock. При concurrency=2 latency выросла, throughput не вырос: backend последовательный. Выборка слишком мала для устойчивого p95.

Prefill обрабатывает входной контекст; decode последовательно порождает новые токены. KV-cache хранит ключи/значения внимания по слоям и растёт с длиной контекста и числом активных последовательностей. Возвращается единый JSON, поэтому измеряется полная задержка: TTFT/ITL не измерялись. Это не benchmark continuous batching/PagedAttention SGLang/vLLM.

## 7. Триггеры и CI

| Событие | Команды/действие |
|---|---|
| Код | make check-hw8910; изменение generation → новая полная оценка |
| Данные | schema check + новый cache key; изменение golden → make evaluate и новый gate; изменение входа только проверки не требует training |
| Новый адаптер | attach_model, проверка файлов/загрузки, полная evaluate, gate, release_flow; лишь затем restart API |

CI выполнен локально, удалённые Actions и защита merge не заявляются. Сохранены красный/зелёный логи. План rollback: выбрать ранее допущенный immutable manifest/report, перепроверить файлы и report, атомарно опубликовать, перезапустить API, сверить реальный loaded_id. Смена accepted.json сама по себе модель в памяти не меняет.

## Доступ и воспроизведение

Код и отчёты — GitHub; evidence/logs/raw benchmark — отдельный release-комплект. Веса, caches, .venv и Docker volumes не входят в Git/архив. Нужные файлы адаптера доступны отдельными release-assets без упаковки весов в архив; их имена совпадают с keys adapter/* в manifest. Base revision загружается из HF. Полные eval и golden доступны в комплекте ДЗ6–7. Быстрые тесты не требуют модели.

Видео 5–8 минут приложено к этому же выпуску. Предыдущие tests/ ДЗ6–7 сохранены; новые tests находятся отдельно hw8910/tests.
