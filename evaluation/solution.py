"""Strict scoring and a fail-closed, zero-regression release gate."""
import json
import math


def _unique(items, label):
    if not isinstance(items, list) or not items:
        raise ValueError(f'{label}: empty/non-list dataset')
    result = {}
    for row in items:
        if not isinstance(row, dict) or not isinstance(row.get('id'), str) or not row['id']:
            raise ValueError(f'{label}: missing string id')
        if row['id'] in result:
            raise ValueError(f'{label}: duplicate id {row["id"]}')
        result[row['id']] = row
    return result


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('Duplicate JSON key')
        result[key] = value
    return result


def _parse(raw):
    if not isinstance(raw, str):
        return None
    try:
        value = json.loads(raw, object_pairs_hook=_pairs)
    except (ValueError, TypeError):
        return None
    if not isinstance(value, dict) or set(value) != {'answer'} or not isinstance(value['answer'], str):
        return None
    return value


def _aggregate(items):
    n = len(items)
    if not n:
        raise ValueError('Empty metric group')
    correct = sum(x['correct'] for x in items)
    valid = sum(x['valid'] for x in items)
    errors = sum(x['error'] is not None for x in items)
    return dict(n=n, correct=correct, valid=valid, errors=errors,
                accuracy=correct / n, format_rate=valid / n)


def score(rows, outputs):
    """Верните overall, slices и per_item. Не удаляйте плохие ответы из знаменателя.

    Строгий ответ: JSON с единственным строковым полем answer из choices.
    outputs: [{id, raw, error, latency_seconds}, ...].
    В overall и каждом срезе: n, correct, valid, errors, accuracy, format_rate.
    В per_item: id, raw, parsed, valid, correct, error, slices.
    Несовпадающие/дублирующиеся id и пустой набор должны вызвать ValueError.
    """
    tasks, answers = _unique(rows, 'rows'), _unique(outputs, 'outputs')
    if tasks.keys() != answers.keys():
        raise ValueError('Task and output ids differ')
    per_item = []
    for key, row in tasks.items():
        choices, slices = row.get('choices'), row.get('slices')
        if not isinstance(choices, list) or not choices or any(not isinstance(x, str) for x in choices):
            raise ValueError('Invalid task choices')
        if not isinstance(row.get('expected'), str) or row['expected'] not in choices:
            raise ValueError('Expected label is not a choice')
        if not isinstance(slices, list) or not slices or any(not isinstance(x, str) or not x for x in slices):
            raise ValueError('Invalid slices')
        output = answers[key]
        if 'raw' not in output or 'error' not in output:
            raise ValueError('Output must contain raw and error')
        raw, error = output['raw'], output['error']
        parsed = _parse(raw)
        valid = error is None and parsed is not None and parsed['answer'] in choices
        per_item.append(dict(id=key, raw=raw, parsed=parsed, valid=valid,
                             correct=valid and parsed['answer'] == row['expected'],
                             error=error, slices=list(dict.fromkeys(slices))))
    names = sorted({s for item in per_item for s in item['slices']})
    return dict(overall=_aggregate(per_item),
                slices={s: _aggregate([x for x in per_item if s in x['slices']]) for s in names},
                per_item=per_item)


def _validate_report(report, label, minimum):
    if not isinstance(report, dict):
        raise ValueError(f'{label}: report must be a dictionary')
    items = _unique(report.get('per_item'), label)
    for item in items.values():
        if type(item.get('valid')) is not bool or type(item.get('correct')) is not bool:
            raise ValueError(f'{label}: flags must be bool')
        if 'error' not in item or 'raw' not in item or 'parsed' not in item:
            raise ValueError(f'{label}: incomplete per_item')
        slices = item.get('slices')
        if not isinstance(slices, list) or not slices or any(not isinstance(x, str) or not x for x in slices) or len(slices) != len(set(slices)):
            raise ValueError(f'{label}: invalid per_item slices')
        if item['correct'] and not item['valid']:
            raise ValueError(f'{label}: correct requires valid')
        if item['valid'] and (item['error'] is not None or _parse(item['raw']) != item['parsed'] or item['parsed'] is None):
            raise ValueError(f'{label}: invalid raw/parsed/error relation')
    names = {s for x in items.values() for s in x['slices']}
    expected = {'overall': _aggregate(list(items.values())),
                'slices': {s: _aggregate([x for x in items.values() if s in x['slices']]) for s in names}}
    if not isinstance(report.get('slices'), dict) or set(report['slices']) != names or len(items) < minimum:
        raise ValueError(f'{label}: missing slices or need {minimum} items')
    for name, counts in [('overall', expected['overall']), *expected['slices'].items()]:
        metric = report.get('overall') if name == 'overall' else report['slices'][name]
        if not isinstance(metric, dict):
            raise ValueError(f'{label}: missing metrics {name}')
        for key, value in counts.items():
            actual = metric.get(key)
            if key in ('n', 'correct', 'valid', 'errors'):
                if type(actual) is not int or actual != value:
                    raise ValueError(f'{label}/{name}: inconsistent {key}')
            elif type(actual) not in (int, float) or not math.isfinite(actual) or not math.isclose(actual, value, abs_tol=1e-12, rel_tol=0):
                raise ValueError(f'{label}/{name}: invalid {key}')
    if report['overall']['errors']:
        raise ValueError(f'{label}: generation errors')
    return items


def quality_gate(baseline, candidate, critical_slices):
    """Верните {passed: True, ...} или вызовите ValueError с причиной отказа.

    Проверьте совместимость протокола/набора/baseline, метрики и counts,
    все id и срезы, общую accuracy/format_rate, критические срезы и behavior.
    Missing, NaN, пустой набор и ошибки генерации означают отказ.
    Пороги задаются до измерения; учебный допуск регрессии равен нулю.
    """
    try:
        for field in ('protocol_sha256', 'golden_sha256', 'baseline_spec_sha256'):
            if not isinstance(baseline.get(field), str) or not baseline[field] or baseline[field] != candidate.get(field):
                raise ValueError(f'Incompatible {field}')
        for report in (baseline, candidate):
            if report.get('status') != 'complete' or not isinstance(report.get('model'), dict) or not report['model'].get('kind'):
                raise ValueError('Incomplete report or model identity')
            model = report['model']
            if model['kind'] == 'base' and (not model.get('name') or not isinstance(model.get('revision'), str) or len(model['revision']) != 40):
                raise ValueError('Base model needs a name and exact revision')
            if model['kind'] == 'adapter' and any(not model.get(k) for k in ('name', 'version', 'run_id', 'uri')):
                raise ValueError('Adapter needs a concrete registry version and run')
        a = _validate_report(baseline, 'baseline', 50)
        b = _validate_report(candidate, 'candidate', 50)
        if a.keys() != b.keys() or baseline['slices'].keys() != candidate['slices'].keys() or len(baseline['slices']) < 3:
            raise ValueError('Golden ids/slices differ or fewer than 3 slices')
        for key in a:
            if set(a[key]['slices']) != set(b[key]['slices']):
                raise ValueError('Per-item slice membership differs')
        if not isinstance(critical_slices, list) or not critical_slices or not set(critical_slices) <= baseline['slices'].keys():
            raise ValueError('Missing/invalid critical slices')
        for key in ('accuracy', 'format_rate'):
            if candidate['overall'][key] < baseline['overall'][key]:
                raise ValueError(f'Overall regression: {key}')
        for name in critical_slices:
            if candidate['slices'][name]['accuracy'] < baseline['slices'][name]['accuracy']:
                raise ValueError(f'Critical slice regression: {name}')
        for label, report in [('baseline', baseline), ('candidate', candidate)]:
            _validate_report(report.get('behavioral'), label + '/behavioral', 3)
        ca = candidate['behavioral']['overall']
        if ca['correct'] != ca['n'] or ca['valid'] != ca['n']:
            raise ValueError('Candidate failed required behavioral cases')
        if baseline['behavioral']['overall']['n'] != ca['n'] or {x['id'] for x in baseline['behavioral']['per_item']} != {x['id'] for x in candidate['behavioral']['per_item']}:
            raise ValueError('Behavioral ids differ')
        return dict(passed=True, tolerance=0, critical_slices=critical_slices,
                    baseline_accuracy=baseline['overall']['accuracy'],
                    candidate_accuracy=candidate['overall']['accuracy'])
    except (KeyError, TypeError, AttributeError) as exc:
        raise ValueError(f'Malformed evaluation report: {exc}') from exc
