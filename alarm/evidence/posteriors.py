from dataclasses import dataclass
from decimal import Decimal
from alarm.evidence.timeline import EvidenceInterval
from alarm.evidence.operators import waiting_operator, mark_operator
from alarm.evidence.propagation import normalize_evidence, EvidenceNumericalError
from alarm.evidence.matrix import row_matrix_multiply


@dataclass(frozen=True)
class PosteriorResult:
    times: tuple
    probabilities: tuple


def backward_messages(plan, time):
    column = [Decimal(1)] * len(plan.model.states)
    for step in reversed(plan.steps):
        if isinstance(step, EvidenceInterval):
            if step.end <= time:
                continue
            operator = waiting_operator(plan.model, step.end - max(time, step.start))
        else:
            if step.time <= time:
                continue
            operator = mark_operator(plan.model, step.kind)
        column = [sum(value * column[j] for j, value in enumerate(row))
                  for row in operator]
        scale = max(column)
        if scale <= 0 or any(x < 0 or not x.is_finite() for x in column):
            raise EvidenceNumericalError('invalid backward message')
        column = [x / scale for x in column]
    return tuple(column)


def smooth_posteriors(evidence, queries):
    plan = evidence.plan
    answers = []
    for time in queries:
        row = tuple(plan.model.initial)
        for step in plan.steps:
            if isinstance(step, EvidenceInterval):
                if step.start >= time:
                    continue
                operator = waiting_operator(plan.model, min(time, step.end) - step.start)
            else:
                if step.time > time:
                    continue
                operator = mark_operator(plan.model, step.kind)
            row, _ = normalize_evidence(row_matrix_multiply(row, operator))
        backward = backward_messages(plan, time)
        posterior, _ = normalize_evidence([a * b for a, b in zip(row, backward)])
        answers.append(posterior)
    return PosteriorResult(tuple(queries), tuple(answers))
