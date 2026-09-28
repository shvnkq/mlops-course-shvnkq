# MLOPS-26: домашняя работа 3

Воспроизводимый DVC-пайплайн собственного датасета **GeoNames City Facts RU**:

```text
GeoNames → collect → clean → diversity → split → contamination check
```

Исходные структурированные факты берутся из закреплённого в `uv.lock` пакета
`geonamescache==3.0.2` и переразмечаются в русскоязычный chat JSONL. Данные не
хранятся в Git: DVC использует локальный remote `../dvc_remote`.

## Запуск

```bash
uv sync
make repro
make check-hw3
```

Управление версиями и проверки:

```bash
make v1             # 80 стран, 320 городов, 1280 сырых примеров
make v2             # 100 стран, 500 городов, 2000 сырых примеров
make diff           # разница метрик workspace и Git
make diversity      # гейт разнообразия
make contamination  # пересечения train/test
make dag            # граф DVC
```

Для явного сравнения зафиксированных версий:

```bash
uv run dvc metrics diff hw3-v1 hw3-v2
```

## Результат v2

- 1915 примеров после очистки;
- 100 групп-стран и 5 системных промптов;
- split: 1536 train / 188 val / 191 test;
- контаминация train/test: 0 по всем четырём проверкам;
- near-dup: удалено 83 строки;
- все восемь пунктов `make check-hw3` проходят.

Подробности: [паспорт датасета](docs/datasheet.md),
[разбор дефектов](docs/defects.md), [источник и лицензия](SOURCE.md).

## ДЗ 4 — токенизация для обучения

Стадия `tokenize` продолжает граф DVC после `split`. Вход — собственные
`data/train.jsonl` и `data/val.jsonl` из ДЗ 3; для самой токенизации модель
не загружается, используется только `Qwen/Qwen3-0.6B` tokenizer.

```bash
uv sync
make tokenize       # тензоры, метрики и генерируемый отчёт
make check          # девять проверок ДЗ 4
uv run dvc repro tokenize
```

На Windows цель `check` запускает Git Bash, а не WSL. Результат:
1536 train и 188 val примеров, `max_seq_len = 144`, обрезка 0%,
левый динамический паддинг, 45743 обучаемых токена из 136977 в train.
Packing выключен, поскольку блочная attention-маска здесь не реализована.

Числа и прогноз времени: [отчёт tokenize](docs/tokenize_report.md),
[метрики](metrics/tokenize.json). Исправления четырёх дефектов подробно
описаны в разделе ДЗ 4 [разбора дефектов](docs/defects.md).

Токенизированные файлы находятся в `data/tokenized/` под DVC; Git хранит
код, параметры, `dvc.lock`, метрики и отчёт, но не сами данные или тензоры.
