"""Finite analytic examples, not a general interval inference implementation."""
from copy import deepcopy
from decimal import Decimal as D, localcontext
import json


def cases():
    switch = {
        'definition': {'states': ['before', 'after'],
                       'Q': [[-1, 1], [0, 0]], 'initial': [1, 0],
                       'intensities': {'a': [1, 0], 'b': [0, 1]}},
        'changes': [
            {'alarm_id': 'left', 'source_revision': 1, 'action': 'put',
             'interval': [D(0), D(1)], 'kind': 'a'},
            {'alarm_id': 'right', 'source_revision': 1, 'action': 'put',
             'interval': [D(0), D(1)], 'kind': 'b'}],
        'T': D(1), 'queries': [D(1), D('.25'), D('.75')],
        'windows': [
            {'state': 'after', 'start': D(0), 'end': D('.5'), 'label': 'early'},
            {'state': 'after', 'start': D('.5'), 'end': D(1), 'label': 'late'}]}
    static = {
        'definition': {'states': ['idle', 'hot'],
                       'Q': [[0, 0], [0, 0]], 'initial': [D('.4'), D('.6')],
                       'intensities': {'a': [1, 2], 'b': [D('.5'), D('.25')]}},
        'changes': [
            {'alarm_id': 'first', 'source_revision': 1, 'action': 'put',
             'interval': [D(0), D('.5')], 'kind': 'a'},
            {'alarm_id': 'second', 'source_revision': 1, 'action': 'put',
             'interval': [D('.25'), D(1)], 'kind': 'a'}],
        'T': D(1), 'queries': [D(1), D('.5'), D(0)],
        'windows': [
            {'state': 'idle', 'start': D(0), 'end': D('.7'), 'label': 'idle'},
            {'state': 'hot', 'start': D('.2'), 'end': D(1), 'label': 'hot'}]}
    rare = deepcopy(static)
    rare['definition']['intensities'] = {'a': [D('1e-300'), D('2e-300')],
                                         'b': [0, 0]}
    return {'switch': switch, 'static': static, 'rare': rare}


def _multiply(a, b):
    out = [D(0)] * (len(a) + len(b) - 1)
    for i, x in enumerate(a):
        for j, y in enumerate(b):
            out[i + j] += x * y
    return out


def _integral(coefficients, lo, hi):
    # Elementary antiderivative of polynomial(u)*exp(-u).
    tail, anti = D(0), []
    for power in range(len(coefficients) - 1, -1, -1):
        tail = D(coefficients[power]) + (power + 1) * tail
        anti.insert(0, tail)
    def primitive(x):
        value = D(0)
        for coefficient in reversed(anti):
            value = value * x + coefficient
        return -(-x).exp() * value
    return primitive(hi) - primitive(lo)


def expected(name):
    with localcontext() as ctx:
        ctx.prec = 100
        case = cases()[name]
        if name == 'switch':
            weight = [D(0), D(1), D(-1)]
            mass = _integral(weight, D(0), D(1))
            pieces = [(D(0), D('.5'), [D('.5'), D(-1)], [D('.5')]),
                      (D('.5'), D(1), [D(0)], [D(1), D(-1)])]
            means = [sum(_integral(_multiply(weight, p[2 + i]), p[0], p[1])
                         for p in pieces) / mass for i in range(2)]
            covariance = [[
                sum(_integral(_multiply(_multiply(weight, p[2 + i]), p[2 + j]),
                              p[0], p[1]) for p in pieces) / mass - means[i] * means[j]
                for j in range(2)] for i in range(2)]
            after = [_integral(weight, D(0), t) / mass for t in case['queries']]
            return {'log_likelihood': -D(1) + mass.ln(),
                    'posteriors': [[1 - p, p] for p in after],
                    'means': means, 'covariance': covariance}
        definition = case['definition']
        prior = definition['initial']
        rates = definition['intensities']
        width = (case['changes'][0]['interval'][1] - case['changes'][0]['interval'][0]) * (
            case['changes'][1]['interval'][1] - case['changes'][1]['interval'][0])
        log_weights = [
            D(prior[s]).ln() - case['T'] * sum(D(row[s]) for row in rates.values())
            + 2 * D(rates['a'][s]).ln() + width.ln() for s in range(2)]
        offset = max(log_weights)
        weights = [(v - offset).exp() for v in log_weights]
        mass = sum(weights)
        probabilities = [w / mass for w in weights]
        rewards = [[(w['end'] - w['start']) if state == w['state'] else D(0)
                    for state in definition['states']] for w in case['windows']]
        means = [sum(p * r for p, r in zip(probabilities, row)) for row in rewards]
        covariance = [[sum(probabilities[s] * rewards[i][s] * rewards[j][s]
                           for s in range(2)) - means[i] * means[j]
                       for j in range(2)] for i in range(2)]
        return {'log_likelihood': offset + mass.ln(),
                'posteriors': [list(probabilities) for _ in case['queries']],
                'means': means, 'covariance': covariance}


def assert_expected(report, name):
    expected_values = expected(name)
    def compare(actual, reference):
        if isinstance(reference, list):
            assert len(actual) == len(reference), (actual, reference)
            for a, b in zip(actual, reference):
                compare(a, b)
        else:
            assert isinstance(actual, D), type(actual)
            assert abs(actual - reference) <= D('1e-8'), (actual, reference)
    for field, value in expected_values.items():
        compare(report[field], value)


def main():
    from alarm.archive.reports import encode_report
    print(json.dumps(json.loads(encode_report(
        {name: {'input': case, 'expected': expected(name)}
         for name, case in cases().items()})), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
