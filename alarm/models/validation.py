from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from alarm.models.types import ModelDefinition, identifier, number, exact_precision

MODEL_VALIDATION_TOLERANCE = Decimal(0)


class ModelValidationError(ValueError):
    pass


def validate_model(states, Q, initial, intensities):
    try:
        states = tuple(identifier(s) for s in states)
        n = len(states)
        if not 2 <= n <= 4 or len(set(states)) != n:
            raise ValueError('expected two to four unique ordered states')
        Q = tuple(tuple(number(v) for v in row) for row in Q)
        initial = tuple(number(v) for v in initial)
        if len(Q) != n or any(len(row) != n for row in Q) or len(initial) != n:
            raise ValueError('model shape mismatch')
        if not isinstance(intensities, dict) or len(intensities) != 2:
            raise ValueError('exactly two alarm types required')
        rates = tuple(sorted((identifier(k), tuple(number(x) for x in row))
                             for k, row in intensities.items()))
        if any(len(row) != n for _, row in rates):
            raise ValueError('intensity shape mismatch')
        model = ModelDefinition(states, Q, initial, rates)
        with localcontext() as ctx:
            ctx.prec = exact_precision(model.numbers())
            ctx.Emax = MAX_EMAX
            ctx.Emin = MIN_EMIN
            if any(x < 0 for x in initial) or sum(initial) != 1:
                raise ValueError('initial probabilities must sum exactly to one')
            for i, row in enumerate(Q):
                if any(x < 0 for j, x in enumerate(row) if j != i):
                    raise ValueError('negative off-diagonal rate')
                if sum(row) != 0:
                    raise ValueError('generator rows must sum exactly to zero')
            if any(x < 0 for _, row in rates for x in row):
                raise ValueError('negative alarm intensity')
        return model
    except (ValueError, TypeError, KeyError, ArithmeticError) as exc:
        raise ModelValidationError(str(exc)) from exc
