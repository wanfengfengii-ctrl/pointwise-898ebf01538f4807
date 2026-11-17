from decimal import Decimal
from alarm.evidence.matrix import matrix_exponential


def silence_generator(model):
    n = len(model.states)
    result = [list(row) for row in model.Q]
    for i in range(n):
        result[i][i] -= sum(row[i] for _, row in model.intensities)
    return result


def waiting_operator(model, duration):
    if duration < 0:
        raise ValueError('negative waiting duration')
    return matrix_exponential([[value * duration for value in row]
                               for row in silence_generator(model)])


def mark_operator(model, kind):
    values = model.rates(kind)
    return [[values[i] if i == j else Decimal(0)
             for j in range(len(values))] for i in range(len(values))]
