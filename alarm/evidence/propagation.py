from dataclasses import dataclass
from decimal import Decimal
from alarm.evidence.timeline import EvidenceInterval
from alarm.evidence.operators import waiting_operator, mark_operator
from alarm.evidence.matrix import row_matrix_multiply


class ImpossibleEvidence(ValueError):
    pass


class EvidenceNumericalError(ArithmeticError):
    pass


@dataclass(frozen=True)
class ForwardCheckpoint:
    time: Decimal
    weights: tuple
    log_scale: Decimal


@dataclass(frozen=True)
class EvidenceResult:
    plan: object
    log_likelihood: Decimal
    terminal: tuple
    checkpoints: tuple


def evidence_has_support(plan):
    model = plan.model
    reachable = {i for i, p in enumerate(model.initial) if p > 0}
    for step in plan.steps:
        if isinstance(step, EvidenceInterval):
            if step.end > step.start:
                pending = list(reachable)
                while pending:
                    i = pending.pop()
                    for j, rate in enumerate(model.Q[i]):
                        if i != j and rate > 0 and j not in reachable:
                            reachable.add(j)
                            pending.append(j)
        else:
            rates = model.rates(step.kind)
            reachable = {i for i in reachable if rates[i] > 0}
        if not reachable:
            return False
    return bool(reachable)


def normalize_evidence(row):
    if any(not x.is_finite() or x < 0 for x in row):
        raise EvidenceNumericalError('invalid evidence propagation')
    mass = sum(row)
    if mass <= 0:
        raise EvidenceNumericalError('positive evidence lost numerically')
    return tuple(x / mass for x in row), mass.ln()


def propagate_evidence(plan):
    if not evidence_has_support(plan):
        raise ImpossibleEvidence('observation has zero path support')
    row = tuple(plan.model.initial)
    log_scale = Decimal(0)
    checkpoints = [ForwardCheckpoint(Decimal(0), row, log_scale)]
    for step in plan.steps:
        if isinstance(step, EvidenceInterval):
            operator = waiting_operator(plan.model, step.end - step.start)
            time = step.end
        else:
            operator = mark_operator(plan.model, step.kind)
            time = step.time
        row, increment = normalize_evidence(row_matrix_multiply(row, operator))
        log_scale += increment
        checkpoints.append(ForwardCheckpoint(time, row, log_scale))
    return EvidenceResult(plan, log_scale, row, tuple(checkpoints))
