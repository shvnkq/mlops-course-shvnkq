# MLOPS-26: ДЗ8–10 — безопасный выпуск и API

Текущая работа находится в `hw8910/`. [Отчёт](hw8910/REPORT.md),
[семь причин и исправлений](hw8910/defects.csv),
[переносимый комплект и видео](https://github.com/shvnkq/mlops-course-shvnkq/releases/tag/hw8910-v1).
Исходная версия сохранена коммитом `d3b6058`; старые тесты ДЗ6–7 не удалялись.

```sh
export PATH="$HOME/.local/bin:$PATH"
uv sync --frozen
make check-hw8910                # 13 исходных + 7 интеграционных; без модели
HW8910_HTTP_ENTRY=api.py make check-hw8910  # те же HTTP-тесты на FastAPI stub
uv run python hw8910/attach_model.py       # готовый training run, не обучение
make release-hw8910              # локальный Prefect flow и связанный gate
make serve-hw8910                # FastAPI, http://127.0.0.1:8091
uv run python hw8910/measure.py  # 8+8 запросов, все попытки сохранены
```

Для attach_model/flow нужен запущенный MLflow ДЗ6–7 (`colima start`, `make up`),
исходные data/metrics и его постоянные тома на этом компьютере. На другом
компьютере можно восстановить `hw8910/state/` из комплекта и отдельных assets
адаптера текущего выпуска: файлы весов и токенизатора скачиваются по одному
в `state/adapter/`; manifest/accepted/release-report — из evidence/ в комплекте.
Веса не находятся в Git и не упакованы в архив сдачи. Для нового gate нужны
полные metrics/ из комплекта ДЗ6–7; исходные source hash проверяются.
Все data/ доступны через локальный DVC remote `dz8-10/dvc_remote`; это не
публичное облако. Полные golden/raw-eval отдельно доступны в выпуске hw67-v1.

`evidence/` содержит JSON-доказательства; сырые .log доступны в комплекте
сдачи. Red/green интеграции воспроизводятся через HW8910_PROJECT, указывающий
на извлечённый исходный hw8910-broken из архива преподавателя. Новый fault
hook не засчитывается как один из шести сопоставимых красных сценариев.
Prefect использует локальное дисковое хранение результатов. Быстрые тесты
не импортируют Prefect/Transformers. Не удаляйте тома MLflow и state модели.

Ниже — исторические инструкции предыдущего ДЗ6–7.

## ДЗ6–7 — эксперименты и проверенный адаптер

Продолжение собственного GeoNames City Facts RU v2 и тензоров ДЗ4/5.
На новом MacBook Air M5 выполнен один sweep: **6 конфигураций × 4 шага**,
весь поиск с упаковкой MLflow занял **100.2 секунды**. Многочасового обучения нет.

Выбран `all-r8-high`: r=8, LR=0.0003, все 7 проекций; val **1.902950 → 1.119799**.
На 60 golden-вопросах baseline дал **2/60**, candidate **35/60** верных
строго форматированных ответов. Три behavioral прошли, регрессий по критическим
срезам нет. Гейт пройден, **candidate и champion указывают на версию 1**
`geonames-qwen-adapter`. Слабый результат на части вопросов и влияние JSON-формата
не скрываются; это не доказательство готовности универсального географического сервиса.

- [Единый вывод A+B](docs/conclusion.md)
- [Шесть runs из MLflow](docs/comparison.csv), [кривые](docs/sweep-curves.png)
- [Четыре исправления](docs/defects.md#дз-67-четыре-исправленных-дефекта)
- [Протокол до измерения](docs/evaluation-plan.md)
- [Проверка всех 60 эталонов](docs/golden-review.md), [линия данных](docs/eval-lineage.json)
- [Переносимый комплект и видео](https://github.com/shvnkq/mlops-course-shvnkq/releases/tag/hw67-v1)

## На этом Mac: проверить выполненную работу

Все команды ниже — из папки `dz6-7/mlops-course-shvnkq`.
uv, Docker CLI, Compose, Colima и Lima установлены в пользовательский каталог;
системные настройки shell не переписывались.

```sh
export PATH="$HOME/.local/bin:$PATH"
colima start --vm-type vz --cpu 2 --memory 2 --disk 20
uv sync --frozen
make up
make check-all       # 9 проверок, затем 24 теста; sweep не повторяется
make eval            # пересчёт допуска по уже сохранённым raw-ответам
make check-negative  # порча только копии ответов -> ожидаемый отказ
```

UI: [MLflow](http://127.0.0.1:5006/#/experiments/1).
`runs/check-all.log` хранит успешную приёмку, отпечаток **c42ac7788026**.
Все выданные файлы `tests/` неизменны. Ещё 5 edge-тестов расположены отдельно:
`uv run python -m scripts.test_solution_extra`. Эти тесты синтетические;
реальные ответы находятся в MLflow и приложении сдачи.

## Повторить эксперимент с нуля

Python 3.12, uv, Docker-совместимый сервер с Compose. Используйте **новую папку**
и отдельный MLflow-сервер/тома для независимого повторения, чтобы не менять
принятую здесь версию и закреплённый baseline.

```sh
uv sync --frozen
uv run dvc pull data.dvc
make check-eval
make up
make sweep
make report
make candidate
make baseline-init  # только один раз; отказывается переписывать baseline
make evaluate
make eval
make check-negative
make promote        # только после PASS; сам заново проверяет gate
make check-storage
make conclusion
make check-all
make conclusion
make package
```

В случае отказа `make eval`/`promote` завершаются ненулевым кодом. Не подавляйте
его и не меняйте пороги: сохраните отказ, пропустите promote, оставьте champion
прежним. `baseline-update` не выполнялся: baseline остаётся исходной Qwen с
точной HF-ревизией `c1899de289a04d12100db370d81485cdf75e47ca`.

Тензоры — точные копии ДЗ4/5, а не повторная токенизация и не датасет курса.
Индекс содержит все 1536 train ID, совпадающие с PT. Golden — 60 вопросов из
test, отдельные страны, 20 country/20 population/20 timezone; метки A/B/C
по 20. Во время sweep выбирались одинаковые первые 32 train и 8 val.
Golden не участвовал в выборе кандидата. Проверка по group_id/строкам не
доказывает отсутствия любых смысловых утечек.

## Данные и перенос со старого ноутбука

Git хранит код, конфиг, baseline, data.dvc и отчёты. Веса, training PT,
`.venv`, MLflow volumes и `metrics/` **не входят в Git**.
DVC remote `local` указывает на `../../dvc_remote` относительно `.dvc/config`,
то есть на `dz6-7/dvc_remote` на этом компьютере. Это локальный, не облачный
remote. Для полного `dvc pull` на другой машине передайте этот каталог и
настройте путь `uv run dvc remote modify local url <путь>`.

Для проверки оценки без весов скачайте комплект из Releases: в нём есть
golden/behavioral, полный training-index, raw-ответы, метрики, diff, гейты,
storage proof и журналы. Набор доступен преподавателю отдельно от локального
DVC remote. В комплекте нет весов и тензоров обучения.

PostgreSQL и файлы моделей живут в разных named volumes Colima. `make down`
сохраняет их, **down -v и удаление VM уничтожат локальный серверный экземпляр**.
Архив Git сам по себе не переносит MLflow DB/volumes на следующий ноутбук.
Пересоздание только контейнера уже проверено реальным probe со сверкой SHA-256.

История Git восстановлена с GitHub после переноса. Артефакты и конспекты ДЗ3–5
сохранены; исторические DVC-файлы и проверки ДЗ5 лежат в `history/hw5/`
и больше не активируют старое многочасовое обучение.
