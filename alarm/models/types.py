from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError('expected a non-boolean finite number')
    result = value if isinstance(value, Decimal) else Decimal(str(value))
    if not result.is_finite():
        raise ValueError('number must be finite')
    return result


def identifier(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError('identifier must be a nonempty string')
    return value


def exact_precision(values):
    values = tuple(values)
    if not values:
        return 80
    high = max(v.adjusted() for v in values if v) if any(values) else 0
    low = min(v.as_tuple().exponent for v in values)
    return max(80, high - low + 20)


def decimal_text(value):
    if not value:
        return '0'
    with localcontext() as ctx:
        ctx.prec = max(1, len(value.as_tuple().digits))
        ctx.Emax = MAX_EMAX
        ctx.Emin = MIN_EMIN
        return str(value.normalize())


@dataclass(frozen=True)
class ModelDefinition:
    states: tuple
    Q: tuple
    initial: tuple
    intensities: tuple

    def rates(self, kind):
        for name, values in self.intensities:
            if name == kind:
                return values
        raise KeyError(kind)

    def numbers(self):
        return tuple(x for row in self.Q for x in row) + self.initial + tuple(
            x for _, row in self.intensities for x in row)


@dataclass(frozen=True)
class ModelRevision:
    model_id: str
    revision: int
    definition: ModelDefinition


@dataclass(frozen=True)
class ModelReceipt:
    model_id: str
    revision: int
    request_id: str
