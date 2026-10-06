"""Build the HW5 results and defect report from actual local artifacts."""

import hashlib
import json
import math
import re
from datetime import datetime
from pathlib import Path

from src.config import load_params
from src.train import inputs_fingerprint

ROOT = Path(__file__).resolve().parents[1]
MARKER = "# ДЗ 5: первый LoRA-ран на собственном датасете"


def read(path):
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def duration(seconds):
    seconds = round(seconds)
    return f"{seconds // 3600} ч {(seconds % 3600) // 60} мин {seconds % 60} с"


def windows(curve):
    k = max(1, len(curve) // 5)
    return sum(x[1] for x in curve[:k]) / k, sum(x[1] for x in curve[-k:]) / k, k


def main():
    params = load_params()
    fingerprint = inputs_fingerprint(params)
    a, f = read("metrics/train_all_layers.json"), read("metrics/train_freeze14.json")
    for m in (a, f):
        assert m["completed"] and m["steps"] == m["planned_steps"] == 192
        assert m["inputs_fingerprint"] == fingerprint, "Training artifacts are stale"
        assert len(m["curve_val"]) == 21 and m["curve_val"][0][0] == 0
        assert m["processed_train_tokens"] == 136977
        assert all(math.isfinite(x[1]) for x in m["curve_train"] + m["curve_val"])
        for key, source in m["source_data"].items():
            assert hashlib.sha256((ROOT / source["path"]).read_bytes()).hexdigest() == source["sha256"]
        cfg = read(str(Path(m["adapter_dir"]) / "adapter_config.json"))
        assert cfg["layers_to_transform"] == list(range(m["freeze_first"], 28))
    comparison = read("metrics/compare_all_layers.json")
    assert len(comparison["base"]) == len(comparison["adapter"]) == len(params["compare"]["prompts"]) == 5
    refs = {}
    for line in (ROOT / "data/val.jsonl").read_text(encoding="utf-8").splitlines():
        r = json.loads(line)
        q = next(x["content"] for x in r["messages"] if x["role"] == "user")
        refs[q] = r["messages"][-1]["content"]
    expected = [refs[p] for p in params["compare"]["prompts"]]
    exact_base = sum(x.strip() == y.strip() for x, y in zip(comparison["base"], expected))
    exact_adapter = sum(x.strip() == y.strip() for x, y in zip(comparison["adapter"], expected))
    ah, at, k = windows(a["curve_train"])
    fh, ft, _ = windows(f["curve_train"])
    speedup = (1 - f["seconds"] / a["seconds"]) * 100
    state_path = ROOT / "runs/status.json"
    state = read("runs/status.json") if state_path.exists() else {}
    if state.get("state") == "completed":
        elapsed = (datetime.fromisoformat(state["finished_at"]) - datetime.fromisoformat(state["started_at"])).total_seconds()
        timing = f"Старт: {state['started_at']}; окончание: {state['finished_at']}. Общая длительность: **{duration(elapsed)}**."
    else:
        timing = f"Сумма времени двух вариантов по метрикам: **{duration(a['wall_seconds'] + f['wall_seconds'])}**. Журнал независимого runner отсутствует или не завершён; календарные отметки не восстанавливаются."
    checker = hashlib.sha256((ROOT / "tests/check.sh").read_bytes()).hexdigest()[:12]
    assert checker == "06a02208c1f0"
    check_log = ROOT / "runs/check.log"
    proof = "Полная самопроверка ещё не завершена."
    repro = "Фиксация seed проверяется двумя короткими прогонами по три шага в make check."
    if check_log.exists():
        text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", check_log.read_text(encoding="utf-8"))
        status_path = ROOT / "runs/check.status.json"
        if status_path.exists() and read("runs/check.status.json")["state"] == "passed":
            assert "Все проверки пройдены." in text and checker in text
            assert "5 ответов совпали дословно" in text
            proof = f"Все девять проверок make check пройдены; неизменённый checker: {checker}."
            match = re.search(r"train loss по шагам: (\[[^\n]+?\]) — одинаково", text)
            assert match, "Missing reproducibility evidence"
            repro = f"Два независимых прогона по три шага дали одинаковую сохранённую кривую train loss: {match.group(1)}. Проверка 5 сравнивает списки точно; метрики train сохраняются с округлением до четырёх знаков. Это подтверждает повторяемость на данной машине на точности журнала, а не побитовую идентичность всех тензоров между платформами."
    results = [
        "# Результаты ДЗ5", "",
        "Все числа ниже прочитаны из артефактов собственного запуска, а не из эталона курса.", "",
        timing, "",
        "Вход: GeoNames City Facts RU v2 из ДЗ3, токенизация ДЗ4; 1536 train и 188 val, без сокращения. "
        "Train содержит 136977 токенов, в лосс идёт 45743. Полный проход — 192 шага оптимизатора при эффективном батче 8.", "",
        "Условия: Ryzen 5 5500U, CPU, float32, 6 потоков, batch_size=1, grad_accum=8, "
        "LR=2e-4, seed=42, gradient checkpointing; val до шага 1, каждые 10 шагов и в конце. "
        "На каждом замере используются все 188 val-примеров; 21 точка val на вариант.", "",
        "| Показатель | all_layers | freeze14 |", "|---|---:|---:|",
        f"| Обучаемые параметры | {a['trainable_params']:,} | {f['trainable_params']:,} |",
        f"| Доля обучаемых | {a['trainable_share']:.4%} | {f['trainable_share']:.4%} |",
        f"| Средний train loss первых/последних {k} шагов | {ah:.4f} → {at:.4f} | {fh:.4f} → {ft:.4f} |",
        f"| Базовый val loss | {a['base_val_loss']:.6f} | {f['base_val_loss']:.6f} |",
        f"| Итоговый val loss | {a['final_val_loss']:.6f} | {f['final_val_loss']:.6f} |",
        f"| Чистое обучение, с | {a['seconds']:.1f} | {f['seconds']:.1f} |",
        f"| Валидация, с | {a['eval_seconds']:.1f} | {f['eval_seconds']:.1f} |",
        f"| Время варианта с оценкой | {duration(a['wall_seconds'])} | {duration(f['wall_seconds'])} |",
        f"| Peak working set, МиБ | {a['peak_memory_mb']:.1f} | {f['peak_memory_mb']:.1f} |",
        f"| Папка адаптера с токенизатором, МиБ | {a['adapter_size_mb']:.2f} | {f['adapter_size_mb']:.2f} |", "",
        f"Заморозка уменьшила число обучаемых параметров на 50%, чистое время обучения — на {speedup:.1f}%. "
        "Разница пиков памяти — около 1 МиБ: заметной экономии в этой метрике не наблюдается. "
        "Измерен peak_wset процесса Windows за время его жизни, включая загрузку модели, а не только память активаций. "
        "Два последовательных запуска не отделяют влияние заморозки от изменения температуры и фоновой нагрузки.", "",
        "Кривые: [curves.png](curves.png). Ответы: [compare.md](compare.md).", "",
        "## Достоверность ответов", "",
        f"Строгое совпадение с исходными ответами val: база {exact_base}/5, адаптер {exact_adapter}/5. "
        "Это проверка строк, а не полноценная оценка семантической точности. Пять вопросов — фиксированные вопросы "
        "из отложенного val, который не участвует в обучении.", "",
    ]
    for i, (q, ref, answer) in enumerate(zip(params["compare"]["prompts"], expected, comparison["adapter"]), 1):
        results += [f"### {i}. {q}", "", f"**Ответ исходного датасета:** {ref}", "", f"**Адаптер:** {answer}", ""]
    results += [
        "Модель освоила формат краткого географического ответа, но продолжает выдумывать факты. "
        "Падение val loss не означает, что её можно использовать как достоверный справочник. "
        "По условию оценивается исправленный воспроизводимый пайплайн; эти ошибки не скрываются.", "",
        "## Проверка и происхождение", "", proof, "", repro, "",
        f"Отпечаток входов обучения: `{fingerprint}`. Исходные тензоры сверены по SHA-256:", "",
        f"- train.pt: `{a['source_data']['train']['sha256']}`",
        f"- val.pt: `{a['source_data']['val']['sha256']}`", "",
        "Код, настройки, dvc.lock, график и текстовые отчёты хранятся в Git. Данные, адаптеры и JSON-метрики "
        "исключены из Git и сохраняются в DVC cache/remote. Журналы и пробные прогоны остаются локально.", "",
    ]
    (ROOT / "docs/hw5_results.md").write_text("\n".join(results), encoding="utf-8")
    defects_path = ROOT / "docs/defects.md"
    old = defects_path.read_text(encoding="utf-8").split(MARKER)[0].rstrip()
    defects = f"""{MARKER}

Вход — собственные тензоры ДЗ4, 1536 train и 188 val. Оба варианта прошли
всю эпоху: по 192 шага, без max_steps и без сокращения датасета. Все числа
ниже относятся к этому запуску на CPU. Подробное сравнение, происхождение
данных и ограничения — в [hw5_results.md](hw5_results.md).

## 1. Валидация отсутствовала: обучение шло вслепую

В заготовке base_val был None, evaluate не вызывался, curve_val оставалась
пустой. Train loss мог снижаться из-за запоминания примеров, а улучшение
относительно базовой модели было невозможно проверить. Теперь evaluate
считает loss на всех 188 val-примерах, взвешивая его числом обучаемых токенов
после сдвига labels. Оценка проходит до обновлений, каждые 10 шагов и на
последнем шаге; eval() отключает dropout, затем режим train() восстанавливается.

Получено по 21 точке val: шаги 0, 10–190 и 192. Базовый loss обоих вариантов
равен {a['base_val_loss']:.6f}; итог all_layers — {a['final_val_loss']:.6f},
freeze14 — {f['final_val_loss']:.6f}. Значения взяты из текущих метрик,
а не из учебного медицинского датасета.

## 2. Learning rate 1e-2 вызывал нестабильные обновления

Исходное значение train.lr было 0.01: в 50 раз больше подходящего для этого
LoRA-прогона 0.0002. Сам факт сохранения адаптера и отсутствие NaN не доказывают
сходимость: слишком большие обновления способны поднять loss до десятков.
LR исправлен на 2e-4; сохранены cosine schedule с warmup 3%, ограничение
нормы градиента 1.0 и проверка конечности loss перед backward.

В полном all_layers средний train loss первых {k} шагов — {ah:.6f}, последних
{k} — {at:.6f}; val снизился с {a['base_val_loss']:.6f} до
{a['final_val_loss']:.6f}. У freeze14 train {fh:.6f} → {ft:.6f},
val {f['base_val_loss']:.6f} → {f['final_val_loss']:.6f}. Все train/val
значения конечны; diverged=false у обоих. Не утверждаем, что запускали
полную дефектную версию с lr=0.01: это причина в исходном коде, а числа
подтверждают исправленный запуск.

## 3. freeze_first не влиял на конфигурацию LoRA

Заготовка принимала freeze_first, но не передавала layers_to_transform.
Адаптеры оставались на всех слоях, поэтому эксперимент сравнивал одинаковые
модели. Теперь для all_layers выбраны слои 0–27, для freeze14 — только 14–27;
базовые веса заморожены в обоих случаях. Non-reentrant checkpointing не
требует принудительных градиентов на входных embedding, что избавляет от
ненужного обратного прохода через нижние замороженные слои.

В adapter_config.json реально сохранён диапазон 14–27. Обучаемых параметров
{f['trainable_params']:,} вместо {a['trainable_params']:,}, ровно вдвое меньше.
Чистое обучение заняло {f['seconds']:.1f} с против {a['seconds']:.1f} с,
выигрыш {speedup:.1f}%; val слегка хуже: {f['final_val_loss']:.6f} против
{a['final_val_loss']:.6f}. Peak working set {f['peak_memory_mb']:.1f} против
{a['peak_memory_mb']:.1f} МиБ — значимой экономии памяти по этому замеру нет;
пик включает загрузку модели. Сравнение времени ограничено условиями
двух последовательных прогонов одного ноутбука.

## 4. Адаптер зависел от токенизатора из внешнего кеша

В train сохранялись только матрицы адаптера, а compare загружал токенизатор
по имени базовой модели. На другой машине папки адаптера не хватало:
шаблон чата и токенизация были неизвестны. Теперь tokenizer.save_pretrained
сохраняет tokenizer.json, tokenizer_config.json, vocab, merges и
chat_template.jinja рядом с весами. compare загружает токенизатор только
из adapter_dir с local_files_only=True и использует общий src/prompt.py
из ДЗ4. В inference_config.json сохранены режим thinking и настройки сравнения.
Базовые веса всё ещё нужны отдельно — адаптер их не содержит.

Вес all_layers в adapter_model.safetensors — 20 236 472 байта; freeze14 —
10 118 112 байт. В ключах safetensors находятся только lora-матрицы, без
embed_tokens/lm_head. Полные папки с токенизатором занимают {a['adapter_size_mb']:.2f}
и {f['adapter_size_mb']:.2f} МиБ. Пробный адаптер был успешно поднят офлайн
на первом этапе. Полная проверка 4 копирует итоговую папку, отключает сеть
и сравнивает все пять ответов дословно; её результат приведён ниже.

## 5. Сид был объявлен, но не применялся перед инициализацией

В заготовке set_seed существовал, но train его не вызывал. Случайная
инициализация LoRA и dropout менялись даже при неизменном порядке батчей.
Теперь setup_runtime вызывается до загрузки модели и создания адаптера:
фиксируются random, numpy, torch и CUDA, seed=42; включены детерминированные
алгоритмы. PYTHONHASHSEED задаётся также при запуске процесса. Порядок
примеров зависит от того же seed, а сравнение использует greedy generation.

{repro}

Входы обоих полных обучений имеют одинаковый отпечаток `{fingerprint}`:
код обучения, версии зависимостей, конфигурация и содержимое train.pt/val.pt
сверены с текущими файлами. Изменение любого из этих входов требует нового
обучения. Выданный tests/check.sh не редактировался; его SHA-256 начинается
с `{checker}`. Windows-обёртка лишь выбирает Git Bash и UTF-8, чтобы не
зависеть от WSL и кодовой страницы терминала.

## Самопроверка и ограничения результата

{proof}

В Git не включены data/, models/ и metrics/*.json; они находятся в DVC.
Для обоих вариантов построены реальные train/val-кривые. В пяти вопросах
из val точное строковое совпадение с исходным ответом: база {exact_base}/5,
адаптер {exact_adapter}/5. Несмотря на падение loss, модель ошибается в
географических фактах. Исправление пайплайна не превращает её в достоверный
справочник; качество генерации показано без отбора удачных ответов.
"""
    defects_path.write_text(old + "\n\n" + defects, encoding="utf-8")
    print(f"Training artifacts current: {fingerprint}; 192 steps x2, 21 val points x2")
    print(f"Exact reference matches: base {exact_base}/5, adapter {exact_adapter}/5")
    print("-> docs/hw5_results.md, docs/defects.md")


if __name__ == "__main__":
    main()
