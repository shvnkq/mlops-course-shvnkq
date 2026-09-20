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
make check
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
- все восемь пунктов `make check` проходят.

Подробности: [паспорт датасета](docs/datasheet.md),
[разбор дефектов](docs/defects.md), [источник и лицензия](SOURCE.md).
