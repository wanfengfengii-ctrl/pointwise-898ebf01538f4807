"""Independent audit for interval conditional analysis.

This reference never imports the production interval propagators, matrix
exponential or occupancy machinery.  Two independent methods are provided:

* ``static_analytic`` for zero-generator models: closed-form state weights
  built directly from the initial distribution, silence survival factors,
  mark intensities and interval widths (no 2! permutation divisor), with
  occupancy moments from the resulting state mixture.
* ``nested_grid`` for general switching models: explicit nested grid
  integration over the ordered placement times combined with an independently
  written scalar Taylor matrix exponential for the silence transitions.

Both are deliberately separate from the production implementation and are
used only by the audit tests.
"""
from decimal import Decimal as D, localcontext


def static_analytic(definition, interval_specs, T, windows):
    """Closed-form reference when the hidden generator is zero."""
    with localcontext() as ctx:
        ctx.prec = 80
        T = D(str(T))
        states = definition['states']
        n = len(states)
        initial = [D(str(x)) for x in definition['initial']]
        rates = {k: [D(str(x)) for x in row]
                 for k, row in definition['intensities'].items()}
        total_rate = [sum(rates[k][s] for k in rates) for s in range(n)]
        width_product = D(1)
        intensity_product = [D(1) for _ in range(n)]
        for lo, hi, kind in interval_specs:
            width_product *= D(str(hi)) - D(str(lo))
            for s in range(n):
                intensity_product[s] *= rates[kind][s]
        log_weights = [
            initial[s].ln() - T * total_rate[s] + intensity_product[s].ln()
            + width_product.ln() for s in range(n)]
        offset = max(log_weights)
        weights = [(value - offset).exp() for value in log_weights]
        mass = sum(weights)
        probability = [value / mass for value in weights]
        means = [D(0)] * len(windows)
        raw = [[D(0) for _ in windows] for _ in windows]
        for w, (wstate, start, end) in enumerate(windows):
            length = D(str(end)) - D(str(start))
            for s, state in enumerate(states):
                if state == wstate:
                    means[w] += probability[s] * length
        for i, (si, ai, bi) in enumerate(windows):
            for j, (sj, aj, bj) in enumerate(windows):
                if j < i:
                    raw[i][j] = raw[j][i]
                    continue
                li, lj = D(str(bi)) - D(str(ai)), D(str(bj)) - D(str(aj))
                for s, state in enumerate(states):
                    if state == si == sj:
                        raw[i][j] += probability[s] * li * lj
        covariance = [[raw[i][j] - means[i] * means[j]
                       for j in range(len(windows))] for i in range(len(windows))]
        return {'log_likelihood': offset + mass.ln(), 'means': means,
                'covariance': covariance,
                'state_probability': tuple(probability)}


def _silence(definition):
    n = len(definition['states'])
    rates = {k: [D(str(x)) for x in row]
             for k, row in definition['intensities'].items()}
    Q = [[D(str(x)) for x in row] for row in definition['Q']]
    return [[Q[i][j] - (sum(rates[k][i] for k in rates) if i == j else 0)
             for j in range(n)] for i in range(n)]


def _mexp(matrix, duration, precision=70):
    """Independent scalar Taylor matrix exponential (row convention)."""
    n = len(matrix)
    scaled = [[matrix[i][j] * duration for j in range(n)] for i in range(n)]
    result = [[D(int(i == j)) for j in range(n)] for i in range(n)]
    term = [row[:] for row in result]
    for order in range(1, 8 * precision + 50):
        term = [[sum(term[i][h] * scaled[h][j] for h in range(n)) / order
                 for j in range(n)] for i in range(n)]
        result = [[result[i][j] + term[i][j] for j in range(n)] for i in range(n)]
        if max(abs(value) for row in term for value in row) < D(1).scaleb(-precision):
            break
    return result


def _row_mul(row, matrix):
    return [sum(row[i] * matrix[i][j] for i in range(len(row)))
            for j in range(len(matrix))]


def nested_grid(definition, interval_specs, exact_specs, T, windows, grid=40, precision=70):
    """Explicit nested grid integration for up to two interval identities."""
    with localcontext() as ctx:
        ctx.prec = precision
        T = D(str(T))
        silence = _silence(definition)
        n = len(definition['states'])
        states = definition['states']
        exact = sorted((D(str(t)), k) for t, k in exact_specs)
        intervals = [(D(str(lo)), D(str(hi)), k) for lo, hi, k in interval_specs]
        if not 1 <= len(intervals) <= 2:
            raise ValueError('audit supports one or two interval identities')
        rates = {k: [D(str(x)) for x in row]
                 for k, row in definition['intensities'].items()}

        def weight_at(placements):
            events = sorted(list(exact) + placements, key=lambda item: item[0])
            row = [D(str(x)) for x in definition['initial']]
            previous = D(0)
            for time, kind in events:
                row = _row_mul(row, _mexp(silence, time - previous, precision))
                row = [row[i] * rates[kind][i] for i in range(n)]
                previous = time
            return _row_mul(row, _mexp(silence, T - previous, precision))

        grids, cells = [], []
        for lo, hi, _ in intervals:
            step = (hi - lo) / grid
            grids.append([lo + (index + 1) * step for index in range(grid)])
            cells.append(step)
        total = [D(0)] * n
        first = [[D(0)] * n for _ in windows]
        second = [[[D(0)] * n for _ in windows] for _ in windows]
        if len(intervals) == 1:
            cell = cells[0]
            for t0 in grids[0]:
                row = weight_at([(t0, intervals[0][2])])
                _accumulate(row, cell, states, windows, total, first, second)
        else:
            cell = cells[0] * cells[1]
            for order in ((0, 1), (1, 0)):
                for t1 in grids[order[0]]:
                    for t2 in grids[order[1]]:
                        if not t1 < t2:
                            continue
                        placements = {order[0]: t1, order[1]: t2}
                        row = weight_at([(placements[i], intervals[i][2])
                                         for i in range(2)])
                        _accumulate(row, cell, states, windows, total, first, second)
        mass = sum(total)
        if mass <= 0:
            return None
        means = [sum(first[w]) / mass for w in range(len(windows))]
        raw = [[sum(second[i][j]) / mass if j >= i else D(0)
                for j in range(len(windows))] for i in range(len(windows))]
        for i in range(len(windows)):
            for j in range(i):
                raw[i][j] = raw[j][i]
        covariance = [[raw[i][j] - means[i] * means[j]
                       for j in range(len(windows))] for i in range(len(windows))]
        return {'log_likelihood': mass.ln(), 'means': means,
                'covariance': covariance, 'mass': mass,
                'state_probability': tuple(value / mass for value in total)}


def _accumulate(row, cell, states, windows, total, first, second):
    n = len(states)
    for state in range(n):
        total[state] += row[state] * cell
    for w, (wstate, start, end) in enumerate(windows):
        length = D(str(end)) - D(str(start))
        for state, state_name in enumerate(states):
            if state_name == wstate:
                first[w][state] += row[state] * cell * length
    for i, (si, _, bi) in enumerate(windows):
        for j in range(i, len(windows)):
            sj, aj, bj = windows[j]
            li = D(str(bi)) - D(str(windows[i][1]))
            lj = D(str(bj)) - D(str(aj))
            for state, state_name in enumerate(states):
                if state_name == si == sj:
                    second[i][j][state] += row[state] * cell * li * lj
