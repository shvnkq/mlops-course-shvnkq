# ДЗ6–7: выбор эксперимента и решение о выпуске

**Решение: кандидат принят.** Gate: {"passed": true, "tolerance": 0, "critical_slices": ["country", "population", "timezone"], "baseline_accuracy": 0.03333333333333333, "candidate_accuracy": 0.5833333333333334}. Champion: {'version': '1', 'run_id': 'dbbef824856a45c9a784bb046d21113a'}.

По val выбран `all-r8-high`: 1.902950 → 1.119799; baseline accuracy 2/60, candidate 35/60. Выбор по loss не подменяет решение по реальным ответам.

## A. Сопоставимые эксперименты

Шесть отдельных FINISHED runs, общий sweep `9bd1220eb2954b60a0414ab65f032155`. Полное время поиска с упаковкой и проверкой загрузки моделей — 100.2 с. Apple M5, 16 ГБ, MPS, bfloat16. По 4 шага, train-пул 32, val 8, batch 1 × accumulation 2; seed 42, val на шагах 0/2/4. Это короткий учебный поиск, не сравнение полностью сошедшихся моделей. Скорость первого run включает прогрев; память — аллокатор MPS, не полная память ноутбука.

| Run | r | LR | target | val до | val после | Время, с | MPS peak, МиБ | Пакет адаптера, МиБ |
|---|---:|---:|---|---:|---:|---:|---:|---:|
| qv-r4-low | 4 | 0.0001 | q/v | 1.902950 | 1.842053 | 11.07 | 2828.75 | 13.11 |
| qv-r4-high | 4 | 0.0003 | q/v | 1.902950 | 1.652935 | 3.85 | 3966.83 | 13.11 |
| qv-r8-low | 8 | 0.0001 | q/v | 1.902950 | 1.749233 | 5.01 | 4020.83 | 15.29 |
| qv-r8-high | 8 | 0.0003 | q/v | 1.902950 | 1.471145 | 3.99 | 3996.83 | 15.29 |
| all-r8-low | 8 | 0.0001 | all 7 | 1.902950 | 1.546190 | 5.38 | 4084.84 | 30.20 |
| all-r8-high | 8 | 0.0003 | all 7 | 1.902950 | 1.119799 | 4.73 | 4054.84 | 30.20 |

[CSV из MLflow](comparison.csv), [кривые](sweep-curves.png).
Порог final/base ≤ 1.0 закреплён до выбора. У лучшего run отношение 0.588454. Зарегистрирован candidate `models:/geonames-qwen-adapter/1`, run `dbbef824856a45c9a784bb046d21113a`. Вызов регистрации с нулевым loss-порогом проверяется отдельно: отказ до любых записей в реестр.

## B. Данные и протокол

60 вопросов (20 country, 20 population, 20 timezone) из test собственного GeoNames City Facts RU v2. Этот test не участвовал в выборе по val. Полный индекс — все 1536 исходных train-вопросов, его ID в том же порядке совпали с ID train.pt. SHA-256 PT совпали с ДЗ4/5. Точные нормализованные пересечения и пересечения групп стран: 0. Это не доказательство отсутствия всех смысловых утечек. Разметка всех 60 строк сверена с исходным снимком, [таблица аудита](golden-review.md). Данные версионированы в data.dvc; переносимое приложение оценки опубликовано отдельно.

Критические срезы и причины выбора записаны до измерения в [evaluation-plan.md](evaluation-plan.md). У обеих моделей одна system-инструкция, greedy decoding, seed 42, disabled thinking, лимит 32 токена. expected не включается в prompt; модель получает вопрос и варианты. Метки A/B/C: по 20. Строго валиден только JSON с единственным строковым answer из choices. Неверные, пустые и аварийные ответы остаются в знаменателе.

Baseline: `{"kind": "base", "name": "Qwen/Qwen3-0.6B", "revision": "c1899de289a04d12100db370d81485cdf75e47ca"}`. Candidate: `{"kind": "adapter", "name": "geonames-qwen-adapter", "version": "1", "run_id": "dbbef824856a45c9a784bb046d21113a", "uri": "models:/geonames-qwen-adapter/1"}`.

Протокол SHA-256: `f270ae6f818c0aa7db5f508c79dcbcfcffe0508a51d836eaa3394f0976a0c625`. Golden SHA-256: `9aa86577cc91be6b10d206da82f7c29db460691102ea2bb5ed8d1f80a977b7d6`.

## Общие метрики и срезы

| Срез | n | base correct | cand correct | base valid | cand valid | base accuracy | cand accuracy |
|---|---:|---:|---:|---:|---:|---:|---:|
| overall | 60 | 2 | 35 | 2 | 35 | 0.0333 | 0.5833 |
| country | 20 | 0 | 20 | 0 | 20 | 0.0000 | 1.0000 |
| geography | 60 | 2 | 35 | 2 | 35 | 0.0333 | 0.5833 |
| population | 20 | 0 | 0 | 0 | 0 | 0.0000 | 0.0000 |
| timezone | 20 | 2 | 15 | 2 | 15 | 0.1000 | 0.7500 |

Общий format rate: база 2/60 = 0.0333; candidate 35/60 = 0.5833. Ошибки генерации: 0 / 0. geography пересекается с тремя тематическими срезами: строки не суммируются повторно.

Исправлены (33): golden-geonames-v2-1816670-country, golden-geonames-v2-1795565-country, golden-geonames-v2-1809858-country, golden-geonames-v2-745044-country, golden-geonames-v2-1815286-country, golden-geonames-v2-3688689-country, golden-geonames-v2-112931-country, golden-geonames-v2-2147714-country, golden-geonames-v2-2158177-country, golden-geonames-v2-323786-country, golden-geonames-v2-750269-country, golden-geonames-v2-311046-country, golden-geonames-v2-2174003-country, golden-geonames-v2-53654-country, golden-geonames-v2-3687925-country, golden-geonames-v2-2063523-country, golden-geonames-v2-124665-country, golden-geonames-v2-314830-country, golden-geonames-v2-3674962-country, golden-geonames-v2-418863-country, golden-geonames-v2-1796236-timezone, golden-geonames-v2-1816670-timezone, golden-geonames-v2-1809858-timezone, golden-geonames-v2-745044-timezone, golden-geonames-v2-1815286-timezone, golden-geonames-v2-112931-timezone, golden-geonames-v2-2147714-timezone, golden-geonames-v2-2158177-timezone, golden-geonames-v2-2174003-timezone, golden-geonames-v2-3687925-timezone, golden-geonames-v2-2063523-timezone, golden-geonames-v2-124665-timezone, golden-geonames-v2-3674962-timezone. Потеряны (0): нет.

## Behavioral и отрицательная проверка

| ID | base correct | candidate correct | candidate raw |
|---|---:|---:|---|
| behavior-format | True | True | { /   "answer": "A" / } |
| behavior-paraphrase | False | True | { /   "answer": "C" / } |
| behavior-refusal | False | True | { /   "answer": "REFUSE" / } |

Format требует только JSON; paraphrase связан с тем же group_id и переставленными вариантами/обновлённой меткой; refusal проверяет запрос о рецепте вне географии. Эти кейсы не увеличивают n golden и не выдаются за независимую статистику.

Испорченная копия ответов отклонена: `{"rejected": true, "reason": "Overall regression: accuracy", "note": "Испорчены сохранённые ответы; реальные веса и alias не менялись"}`. Реальные ответы, веса и alias этим тестом не изменялись.

## Разбор пяти пар реальных ответов

### 1. golden-geonames-v2-1816670-country

К какой стране относится город Beijing согласно GeoNames? / A. China / B. Turkey / C. Colombia / Допустимые метки choices: A, B, C.

Эталон: `A` — China.

База: ````json / { /   "answer": "A" / } / ````; valid=False, correct=False.

Candidate: `{ /   "answer": "A" / }`; valid=True, correct=True.

База уже называла верную метку, но обрамляла JSON в Markdown. Кандидат исправил интерфейсный формат; приобретение нового географического знания здесь не доказано.

### 2. golden-geonames-v2-1796236-population

Какова численность населения города Shanghai в использованном снимке GeoNames? / A. 17494398 / B. 24874500 / C. 18960744 / Допустимые метки choices: A, B, C.

Эталон: `B` — 24874500.

База: ````json / { /   "answer": "REFUSE" / } / ````; valid=False, correct=False.

Candidate: `{ /   "answer": "REFUSE" / }`; valid=False, correct=False.

Ложный отказ на географическом вопросе: JSON синтаксически корректен, но REFUSE отсутствует в choices A/B/C. Это ошибка границы задачи и допустимой метки, а не только оформления JSON.

### 3. golden-geonames-v2-323786-timezone

В каком часовом поясе расположен город Ankara согласно исходным данным? / A. America/Bogota / B. Europe/Istanbul / C. Asia/Shanghai / Допустимые метки choices: A, B, C.

Эталон: `B` — Europe/Istanbul.

База: ````json / { /   "answer": "REFUSE" / } / ````; valid=False, correct=False.

Candidate: `{ /   "answer": "REFUSE" / }`; valid=False, correct=False.

Ложный отказ на географическом вопросе: JSON синтаксически корректен, но REFUSE отсутствует в choices A/B/C. Это ошибка границы задачи и допустимой метки, а не только оформления JSON.

### 4. golden-geonames-v2-1796236-timezone

В каком часовом поясе расположен город Shanghai согласно исходным данным? / A. Europe/Istanbul / B. America/Bogota / C. Asia/Shanghai / Допустимые метки choices: A, B, C.

Эталон: `C` — Asia/Shanghai.

База: ````json / { /   "answer": "C" / } / ````; valid=False, correct=False.

Candidate: `{ /   "answer": "C" / }`; valid=True, correct=True.

База уже называла верную метку, но обрамляла JSON в Markdown. Кандидат исправил интерфейсный формат; приобретение нового географического знания здесь не доказано.

### 5. golden-geonames-v2-1795565-country

В какой стране находится город Shenzhen? Укажи современное название страны. / A. Turkey / B. Colombia / C. China / Допустимые метки choices: A, B, C.

Эталон: `C` — China.

База: ````json / { /   "answer": "C" / } / ````; valid=False, correct=False.

Candidate: `{ /   "answer": "C" / }`; valid=True, correct=True.

База уже называла верную метку, но обрамляла JSON в Markdown. Кандидат исправил интерфейсный формат; приобретение нового географического знания здесь не доказано.

## Ограничения и следующий шаг

Общее сходство слов (BLEU/ROUGE/BERTScore) не гарантирует правильность: почти одинаковая фраза с другой страной или числом фактически неверна. Для этой задачи строгие метки проверяют факт и формат отдельно. LLM-as-judge мог бы оценить свободные объяснения и эквивалентность формулировок, но подвержен позиционному смещению, предпочтению многословия и знаниям собственной модели. Для расширения нужны слепые A/B и B/A, фиксированная рубрика и человеческий разбор спорных случаев. Платные API не использовались.

Все 35 валидных ответов кандидата правильны; у базы правильны все 2 валидных. Существенная часть прироста общей accuracy связана с выполнением JSON-контракта. Это не доказывает сопоставимый рост фактических знаний; основной показатель всё равно считается на всех 60 вопросах, а не только на валидных.

На population обе версии получили 0/20: PASS отражает отсутствие регрессии, а не достаточную полезность этого среза. При реальном выпуске нужен заранее согласованный абсолютный минимум качества, однако в учебном gate он не задан; задним числом правила этой оценки не менялись. Ложные отказы на вопросах своей темы требуют отдельного исправления.

60 строк и три behavioral дают ограниченную оценку. Повторное использование набора для разработки не является независимым аудитом. Увеличивать бюджет до PASS задним числом нельзя. При отказе следующий отдельный эксперимент — обучение формату JSON и новая зафиксированная проверка; baseline в этой работе не заменяется.

## Проверки, сохранность и ссылки

Storage: `{"run_id": "ebc060fbb2ec487ca3e7a0068c8ef730", "sha256": "74a10ed7ff164254b61895d91b0c346cbd07113821fcb6ae6ddeb9910e2dc057", "compose_sha256": "8c05f7a6868b88476eb4304b510515bcde083a0b588323f70f58a170b11a80f9", "project": "mlops-hw6"}`.

Приёмка: 9/9; 24 теста преподавателя пройдены. Отпечаток tests/: `c42ac7788026`.

- [qv-r4-low](http://127.0.0.1:5006/#/experiments/1/runs/dc0a3b73783348b1b0a3d4e4e0ca8350) — `dc0a3b73783348b1b0a3d4e4e0ca8350`
- [qv-r4-high](http://127.0.0.1:5006/#/experiments/1/runs/9693ff9655bb40258689c1243f0306a0) — `9693ff9655bb40258689c1243f0306a0`
- [qv-r8-low](http://127.0.0.1:5006/#/experiments/1/runs/fd13fe61bd984876a6d252af90c1d278) — `fd13fe61bd984876a6d252af90c1d278`
- [qv-r8-high](http://127.0.0.1:5006/#/experiments/1/runs/67e501fcda904903b59b674ff4dcf759) — `67e501fcda904903b59b674ff4dcf759`
- [all-r8-low](http://127.0.0.1:5006/#/experiments/1/runs/aa25414282e84116a8e1344067ad7d53) — `aa25414282e84116a8e1344067ad7d53`
- [all-r8-high](http://127.0.0.1:5006/#/experiments/1/runs/dbbef824856a45c9a784bb046d21113a) — `dbbef824856a45c9a784bb046d21113a`
- [Оценка baseline/candidate](http://127.0.0.1:5006/#/experiments/2/runs/ce237897c74149238a6afd2e2789156d) — `ce237897c74149238a6afd2e2789156d`

Ссылки на локальный MLflow работают на этом компьютере при запущенной Colima/Compose. Отчёты и raw-ответы доступны и в переносимом приложении сдачи, без локального сервера. База PostgreSQL и артефакты находятся в отдельных постоянных named volumes. В Git нет весов, тензоров, окружения и volumes. Не выполняйте docker compose down -v.
