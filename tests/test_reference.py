import unittest
from decimal import Decimal, localcontext
from alarm.archive.storage import ArchiveStore
from tests.support import D, model, analyze, put, window, close_decimal


def series_reference(definition, horizon, changes, windows, pin=None):
    # Independent scalar ODE Taylor coefficients; no production numerical imports.
    with localcontext() as ctx:
        ctx.prec = 110
        T = D(str(horizon))
        Q = [[D(str(x)) for x in row] for row in definition['Q']]
        initial = [D(str(x)) for x in definition['initial']]
        rates = {k: [D(str(x)) for x in row] for k, row in definition['intensities'].items()}
        n, m = len(initial), len(windows)
        events = sorted(changes, key=lambda r: (D(str(r['time'])), r['alarm_id']))
        cuts = {D(0), T}
        cuts.update(D(str(r['time'])) for r in events)
        cuts.update(D(str(w[k])) for w in windows for k in ['start', 'end'])
        if pin is not None:
            cuts.add(pin[0])
        G = [[(Q[i][j] - (sum(row[i] for row in rates.values()) if i == j else 0)) * T
              for j in range(n)] for i in range(n)]
        size = n * (1 + m + m * m)
        values = initial + [D(0)] * (size - n)
        log_mass = D(0)
        def derivative(vector, active):
            out = [D(0)] * size
            for block in range(1 + m + m * m):
                for j in range(n):
                    out[block * n + j] = sum(vector[block * n + i] * G[i][j] for i in range(n))
            for r in range(m):
                for j in range(n):
                    out[(1 + r) * n + j] += vector[j] * active[r][j]
            for r in range(m):
                for s in range(m):
                    block = 1 + m + r * m + s
                    for j in range(n):
                        out[block * n + j] += (vector[(1 + r) * n + j] * active[s][j]
                                                + vector[(1 + s) * n + j] * active[r][j])
            return out
        previous = D(0)
        for time in sorted(cuts):
            if time > previous:
                midpoint = (time + previous) / 2
                active = [[D(int(D(str(w['start'])) <= midpoint < D(str(w['end']))
                                  and definition['states'][j] == w['state'])) for j in range(n)]
                          for w in windows]
                duration = (time - previous) / T
                bound = max(sum(abs(x) for x in row) for row in G) + 2 * m
                pieces = max(1, int(duration * bound * 4) + 1)
                h = duration / pieces
                for _ in range(pieces):
                    total, term = list(values), list(values)
                    for order in range(1, 500):
                        term = [x * h / order for x in derivative(term, active)]
                        total = [x + y for x, y in zip(total, term)]
                        if max(abs(x) for x in term) < D('1e-95'):
                            break
                    else:
                        raise AssertionError('reference series failed to converge')
                    values = total
            for event in events:
                if D(str(event['time'])) == time:
                    diagonal = rates[event['kind']]
                    values = [x * diagonal[i % n] for i, x in enumerate(values)]
                    mass = sum(values[:n])
                    if mass == 0:
                        return None
                    values = [x / mass for x in values]
                    log_mass += mass.ln()
            if pin is not None and time == pin[0]:
                values = [x if i % n == pin[1] else D(0) for i, x in enumerate(values)]
            mass = sum(values[:n])
            if mass == 0:
                return None
            values = [x / mass for x in values]
            log_mass += mass.ln()
            previous = time
        means = [sum(values[(1 + r) * n:(2 + r) * n]) for r in range(m)]
        covariance = []
        for r in range(m):
            row = []
            for s in range(m):
                block = 1 + m + r * m + s
                raw = sum(values[block * n:(block + 1) * n])
                row.append((raw - means[r] * means[s]) * T * T)
            covariance.append(row)
        return log_mass, [x * T for x in means], covariance


class ReferenceTests(unittest.TestCase):
    def test_switching_across_marks(self):
        definition = model(True, {'a': [D('0.2'), D('1.7')], 'b': [D('0.9'), D('0.1')]})
        changes = [put('left', 1, 0, 'b'), put('middle', 1, D('0.45')),
                   put('same', 1, D('0.45')), put('right', 1, 1, 'b')]
        windows = [window(start=D('0.4'), label='later'),
                   window(end=D('0.7'), label='early'),
                   window(end=D('0.7'), label='duplicate')]
        queries = [D(1), D(0), D('0.45'), D('0.2')]
        expected = series_reference(definition, 1, changes, windows)
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 100
            result = analyze(store, definition, changes, queries=queries, windows=windows)
            close_decimal(self, result['log_likelihood'], expected[0])
            for i in range(len(windows)):
                close_decimal(self, result['means'][i], expected[1][i])
                for j in range(len(windows)):
                    close_decimal(self, result['covariance'][i][j], expected[2][i][j])
            for axis, time in enumerate(queries):
                for state in range(2):
                    pinned = series_reference(definition, 1, changes, [], (time, state))
                    probability = D(0) if pinned is None else (pinned[0] - expected[0]).exp()
                    close_decimal(self, result['posteriors'][axis][state], probability)

    def test_stationary_switching_analytic_integral(self):
        rate, T = D('0.8'), D('1.3')
        definition = model(rates={'a': [0, 0], 'b': [0, 0]})
        definition['Q'] = [[-rate, rate], [rate, -rate]]
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 90
            result = analyze(store, definition, T=T, queries=[0, T], windows=[window(end=T)])
            expected_variance = T / (4 * rate) - (1 - (-2 * rate * T).exp()) / (8 * rate * rate)
            close_decimal(self, result['log_likelihood'], D(0))
            close_decimal(self, result['means'][0], T / 2)
            close_decimal(self, result['covariance'][0][0], expected_variance)

    def test_three_and_four_state_axes(self):
        for n in (3, 4):
            states = ['s' + str(i) for i in range(n)]
            Q = [[D(0) for _ in range(n)] for _ in range(n)]
            for i in range(n):
                Q[i][(i + 1) % n] = D('0.3')
                Q[i][i] = D('-0.3')
            definition = {'states': states, 'Q': Q,
                          'initial': [D(1)] + [D(0)] * (n - 1),
                          'intensities': {'a': [D(i + 1) / 10 for i in range(n)],
                                          'b': [D(n - i) / 10 for i in range(n)]}}
            changes = [put('x', 1, D('0.4'))]
            windows = [window(states[-1], 0, 1), window(states[0], D('0.2'), D('0.8'))]
            expected = series_reference(definition, 1, changes, windows)
            with self.subTest(n=n), ArchiveStore.open() as store:
                result = analyze(store, definition, changes, windows=windows)
                close_decimal(self, result['log_likelihood'], expected[0])
                for i in range(2):
                    close_decimal(self, result['means'][i], expected[1][i])
                    for j in range(2):
                        close_decimal(self, result['covariance'][i][j], expected[2][i][j])
