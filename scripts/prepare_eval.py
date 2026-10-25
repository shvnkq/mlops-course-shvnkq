"""Versioned geography evaluation; references are checked against the source snapshot."""
import hashlib
import json
from collections import Counter
from pathlib import Path

import geonamescache

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return [json.loads(x) for x in (ROOT / path).read_text(encoding='utf-8').splitlines() if x.strip()]


def write(path, rows):
    p = ROOT / path
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows), encoding='utf-8')


def digest(p):
    return hashlib.sha256((ROOT / p).read_bytes()).hexdigest()


def main():
    train, test = read('data/train.jsonl'), read('data/test.jsonl')
    index = [dict(id=r['id'], group_id=r['topic'],
                  input=next(m['content'] for m in r['messages'] if m['role']=='user')) for r in train]
    gc = geonamescache.GeonamesCache()
    cities, countries = gc.get_cities(), gc.get_countries()
    def city(row):
        return cities[row['id'].split('-')[2]]
    def fact(row, kind):
        c = city(row)
        return str(c['population']) if kind == 'population' else c['timezone'] if kind == 'timezone' else countries[c['countrycode']]['name']
    golden, audit = [], []
    for kind in ('country', 'population', 'timezone'):
        pool = sorted((r for r in test if r['id'].endswith('-'+kind)),
                      key=lambda r: (-city(r)['population'], r['id']))
        assert len(pool) >= 20
        for j, row in enumerate(pool[:20]):
            correct = fact(row, kind)
            distractors = list(dict.fromkeys(fact(other, kind) for other in pool if fact(other, kind)!=correct))
            assert len(distractors) >= 2
            options = [correct, *distractors[:2]]
            offset = len(golden) % 3
            options = options[offset:] + options[:offset]
            label = 'ABC'[options.index(correct)]
            q = next(m['content'] for m in row['messages'] if m['role']=='user')
            original = row['messages'][-1]['content']
            # Verify the original label against the fixed GeoNames snapshot too.
            assert (f"{int(correct):,}".replace(',', ' ') in original) if kind=='population' else correct in original
            prompt = q + '\n' + '\n'.join(f'{a}. {b}' for a,b in zip('ABC', options)) + '\nДопустимые метки choices: A, B, C.'
            record = dict(id='golden-'+row['id'], group_id=row['topic'], input=prompt,
                          expected=label, choices=['A','B','C'], slices=['geography', kind],
                          source=dict(dataset='GeoNames City Facts RU v2 / held-out test',
                                      package='geonamescache==3.0.2', geonameid=city(row)['geonameid'],
                                      original_id=row['id'], field=kind, source_value=correct))
            golden.append(record)
            audit.append(dict(id=record['id'], city=city(row)['name'], field=kind,
                              expected=label, reference=correct, source_id=record['source']['geonameid']))
    first = golden[0]
    behavior = [dict(first, id='behavior-format', type='format', slices=['behavioral','format'],
                     input=first['input']+'\nНе добавляй пояснений или Markdown, только требуемый JSON.')]
    options = [line for line in first['input'].splitlines() if line[:2] in ('A.','B.','C.')]
    flipped = list(reversed([x[3:] for x in options]))
    answer = first['source']['source_value']
    paraphrase = 'Назови страну, на территории которой расположен '+audit[0]['city']+'.\n'
    paraphrase += '\n'.join(f'{a}. {b}' for a,b in zip('ABC',flipped))+'\nДопустимые метки choices: A, B, C.'
    behavior += [dict(first, id='behavior-paraphrase', type='paraphrase', slices=['behavioral','paraphrase'],
                      input=paraphrase, expected='ABC'[flipped.index(answer)])]
    behavior += [dict(id='behavior-refusal', group_id='out-of-domain-cooking', type='refusal',
                     input='Напиши рецепт яблочного пирога. Допустимая метка choices: REFUSE.',
                     choices=['REFUSE'],expected='REFUSE',slices=['behavioral','refusal'],
                     source='Авторский запрос вне границы географии; правило зафиксировано в system до оценки')]
    from evaluation.contract import validate_golden
    proof = validate_golden(golden,index,behavior)
    import torch
    tensors = torch.load(ROOT/'data/tokenized/train.pt',weights_only=True)
    assert [r['id'] for r in index] == [r['id'] for r in tensors['examples']], 'Train index is not the tokenized train source'
    proof['train_index_ids_match_tensor_ids'] = True
    write('data/eval/golden.jsonl',golden)
    write('data/eval/behavioral.jsonl',behavior)
    write('data/eval/training-index.jsonl',index)
    write('data/eval/reference-audit.jsonl',audit)
    proof.update(dataset='GeoNames City Facts RU v2',
                 train_source_sha256=digest('data/train.jsonl'),
                 heldout_source_sha256=digest('data/test.jsonl'),
                 train_pt_sha256=digest('data/tokenized/train.pt'),
                 val_pt_sha256=digest('data/tokenized/val.pt'),
                 n_reference_checks=len(audit), slices=dict(Counter(s for r in golden for s in r['slices'])),
                 labels=dict(Counter(r['expected'] for r in golden)))
    (ROOT/'docs/eval-lineage.json').write_text(json.dumps(proof,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    review = ['# Проверка разметки golden set','',
              '60 вопросов из test ДЗ3, не из train и не из val выбора кандидата. '
              'Группировка по стране сохранена: ни одна страна golden не встречается в train. '
              'Полный индекс содержит все исходные train-вопросы, а не только пул 32 короткого поиска.','',
              'Эталон каждой строки сверен с отдельной записью закреплённого geonamescache==3.0.2 '
              'и с исходным assistant-ответом собственного датасета. Население относится к этому '
              'снимку и не выдаётся за современную численность. Таблица позволяет проверить '
              'каждое соответствие вручную; независимая человеческая экспертиза не заявляется.','',
              '| ID | Город | Поле | Метка | Исходный факт | GeoNames ID |',
              '|---|---|---|---|---|---|']
    for r in audit:
        review.append(f"| {r['id']} | {r['city']} | {r['field']} | {r['expected']} | {r['reference']} | {r['source_id']} |")
    review += ['', 'Координаты не включены: выбираются три однозначных факта. '
               'Слово «город» не устраняет все омонимы; поэтому источник фиксирует GeoNames ID. '
               'Точное сравнение строк и group_id не доказывает отсутствие всех смысловых утечек. '
               'Повторное использование test этого учебного проекта не является независимым аудитом.']
    (ROOT/'docs/golden-review.md').write_text('\n'.join(review)+'\n',encoding='utf-8')
    print(json.dumps(proof,ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
