"""Numeric propagation for jointly integrated interval identities.

For a fixed ordering of the interval identities, the joint path density is
integrated over every feasible placement time.  Each elementary piece (a span
where the set of placeable identities is constant) is handled by one
block-upper-triangular matrix exponential of size ``n * (k + 1)``:

* diagonal block ``s`` is the silence generator ``S`` (no alarm fires),
* the single super-diagonal block ``s -> s+1`` carries the diagonal mark rate
  of the next identity in the ordering, but only when that identity may be
  placed inside the piece.

Exponentiating ``span *`` this block matrix fills every block ``(r, s)`` with
the correctly time-nested transition from completion stage ``r`` to stage
``s``: every identity fires exactly once, all feasible orderings inside the
piece are covered, and nothing is divided by interval width or by permutation
counts.  Exact alarms multiply every stage block by their mark rate.
"""
from dataclasses import dataclass
from decimal import Decimal
from alarm.evidence.matrix import matrix_exponential
from alarm.evidence.operators import silence_generator, mark_operator
from alarm.evidence.propagation import ImpossibleEvidence, EvidenceNumericalError


@dataclass(frozen=True)
class ForwardCheckpoint:
    time: Decimal
    blocks: tuple          # normalised row vectors, one per completion stage
    log_scale: Decimal


@dataclass(frozen=True)
class BackwardCheckpoint:
    time: Decimal
    blocks: tuple          # normalised column vectors, one per stage
    log_scale: Decimal     # log of the common cut scale factor


@dataclass(frozen=True)
class OrderingMessages:
    ordering: tuple
    log_likelihood: Decimal
    forward: tuple
    backward: tuple


def piece_block_operator(plan, ordering, piece):
    """Block-upper-triangular exponential for one elementary piece."""
    n = len(plan.model.states)
    stages = len(ordering) + 1
    size = n * stages
    silence = silence_generator(plan.model)
    matrix = [[Decimal(0) for _ in range(size)] for _ in range(size)]
    for stage in range(stages):
        for i in range(n):
            for j in range(n):
                matrix[stage * n + i][stage * n + j] = silence[i][j]
    for stage, identity in enumerate(ordering):
        if identity not in piece.active:
            continue
        rates = plan.model.rates(plan.interval_marks[identity].kind)
        for state in range(n):
            matrix[stage * n + state][(stage + 1) * n + state] = rates[state]
    span = piece.end - piece.start
    return matrix_exponential([[value * span for value in row] for row in matrix])


def _split(vector, n, stages):
    return tuple(tuple(vector[stage * n:(stage + 1) * n]) for stage in range(stages))


def _concat(blocks):
    return [value for block in blocks for value in block]


def _rescale(blocks):
    # Divide every block by the largest block mass so entries stay at
    # magnitude at most one while relative block ratios are preserved
    # exactly.  Structurally supported tiny blocks remain nonzero across
    # Decimal's full exponent range; no fixed evidence threshold is used.
    # Returns the log of the scale divisor (largest block mass).
    scale = max(sum(block) for block in blocks).ln()
    if not scale.is_finite():
        raise EvidenceNumericalError('positive interval evidence lost numerically')
    scaled = tuple(tuple((value.ln() - scale).exp() if value else value
                         for value in block) for block in blocks)
    if not any(any(block) for block in scaled):
        raise EvidenceNumericalError('positive interval evidence lost numerically')
    return scaled, scale


def _apply_exact(blocks, plan, events):
    n = len(plan.model.states)
    for event in events:
        operator = mark_operator(plan.model, event.kind)
        blocks = tuple(tuple(value * operator[i % n][i % n]
                             for i, value in enumerate(block))
                       for block in blocks)
    return blocks


def _column_from_operator(operator, vector, n, stages):
    result = [Decimal(0)] * (n * stages)
    for row in range(n * stages):
        result[row] = sum(operator[row][col] * vector[col]
                          for col in range(n * stages))
    return result


def propagate_ordering(plan, ordering):
    from alarm.evidence.interval_plan import interval_has_support
    if not interval_has_support(plan, ordering):
        return None
    n = len(plan.model.states)
    stages = len(ordering) + 1
    blocks = (tuple(plan.model.initial),) + tuple(
        tuple(Decimal(0) for _ in range(n)) for _ in range(len(ordering)))
    log_scale = Decimal(0)
    forward = [ForwardCheckpoint(Decimal(0), blocks, log_scale)]
    piece_iter = iter(plan.pieces)
    mark_iter = iter(plan.mark_cuts)
    piece = next(piece_iter, None)
    marks = next(mark_iter, None)
    while piece is not None or marks is not None:
        next_piece = piece.end if piece is not None else None
        next_mark = marks.time if marks is not None else None
        if next_mark is not None and (next_piece is None or next_mark <= next_piece):
            blocks = _apply_exact(blocks, plan, marks.events)
            blocks, increment = _rescale(blocks)
            log_scale += increment
            forward.append(ForwardCheckpoint(marks.time, blocks, log_scale))
            marks = next(mark_iter, None)
            continue
        operator = piece_block_operator(plan, ordering, piece)
        current = _concat(blocks)
        # Row-vector multiplication against the block operator.
        advanced = [sum(current[col] * operator[col][row]
                        for col in range(n * stages)) for row in range(n * stages)]
        blocks = _split(tuple(advanced), n, stages)
        blocks, increment = _rescale(blocks)
        log_scale += increment
        forward.append(ForwardCheckpoint(piece.end, blocks, log_scale))
        piece = next(piece_iter, None)
    final_mass = sum(blocks[len(ordering)])
    if final_mass <= 0 or not final_mass.is_finite():
        raise EvidenceNumericalError('interval evidence collapsed despite structural support')
    # With max-block rescaling, log_scale holds the product of the per-cut
    # maximum block masses.  The joint likelihood is the final completion-stage
    # block (already on that cumulative scale), whose absolute log is
    # log_scale + ln(final block mass on the scaled grid).
    log_scale += final_mass.ln()
    return ordering, tuple(forward), log_scale


def backward_ordering(plan, ordering, log_likelihood, forward):
    """Backward column messages using each piece operator's transpose.

    Every cut divides the raw backward vectors by the local forward-backward
    joint; the accumulated product of those factors is kept in ``log_scale``,
    so multiplying a checkpoint block by ``exp(log_scale)`` restores the
    unnormalised backward message and the shared evidence denominator.
    """
    n = len(plan.model.states)
    stages = len(ordering) + 1
    # At the horizon every identity must already have fired, so the backward
    # message is supported only on the final completion stage.
    blocks = tuple(tuple(Decimal(1) for _ in range(n)) if stage == len(ordering)
                   else tuple(Decimal(0) for _ in range(n))
                   for stage in range(stages))
    forward_by_time = {point.time: point for point in forward}
    record = []
    log_scale = Decimal(0)

    def scale_at(cut_time, current):
        nonlocal log_scale
        point = forward_by_time[cut_time]
        joint = sum(sum(f * b for f, b in zip(point.blocks[stage], current[stage]))
                    for stage in range(stages))
        if joint <= 0 or not joint.is_finite():
            raise EvidenceNumericalError('invalid backward message')
        scaled = tuple(tuple(value / joint for value in block) for block in current)
        log_scale += joint.ln()
        return BackwardCheckpoint(cut_time, scaled, log_scale)

    record.append(scale_at(plan.T, blocks))
    piece_iter = iter(reversed(plan.pieces))
    mark_iter = iter(reversed(plan.mark_cuts))
    piece = next(piece_iter, None)
    marks = next(mark_iter, None)
    while piece is not None or marks is not None:
        next_piece = piece.start if piece is not None else None
        next_mark = marks.time if marks is not None else None
        if next_mark is not None and (next_piece is None or next_mark >= next_piece):
            blocks = _apply_exact(blocks, plan, marks.events)
            point = scale_at(marks.time, blocks)
            record.append(point)
            blocks = point.blocks
            marks = next(mark_iter, None)
            continue
        operator = piece_block_operator(plan, ordering, piece)
        current = _concat(blocks)
        moved = _column_from_operator(operator, current, n, stages)
        blocks = _split(moved, n, stages)
        point = scale_at(piece.start, blocks)
        record.append(point)
        blocks = point.blocks
        piece = next(piece_iter, None)
    return OrderingMessages(ordering, log_likelihood, forward, tuple(reversed(record)))


def smooth_interval_posteriors(plan, messages):
    """Full-future-evidence posteriors with one shared evidence denominator.

    For every ordering the joint numerator is
    ``f(t, s) * beta(t, s) * exp(beta_log_scale(t))``; summing states, stages
    and orderings yields the same evidence mass as the likelihood.  The
    summation runs in log space so vanishingly small but legal contributions
    survive without intermediate underflow.
    """
    n = len(plan.model.states)
    answers = []
    for query in plan.queries:
        terms = [[] for _ in range(n)]
        for message in messages:
            forward = next(point for point in message.forward if point.time == query)
            backward = next(point for point in message.backward if point.time == query)
            for stage in range(len(plan.interval_marks) + 1):
                for state in range(n):
                    f_value = forward.blocks[stage][state]
                    b_value = backward.blocks[stage][state]
                    if f_value and b_value:
                        terms[state].append(
                            f_value.ln() + b_value.ln() + backward.log_scale)
        offset = max(value for state_terms in terms for value in state_terms)
        numerator = [sum((value - offset).exp() for value in state_terms)
                     for state_terms in terms]
        denominator = sum(numerator)
        answers.append(tuple(value / denominator for value in numerator))
    return tuple(answers)


def propagate_interval(plan):
    """Run every feasible ordering; structural zero is recognised explicitly."""
    messages = []
    log_values = []
    for ordering in plan.orderings:
        result = propagate_ordering(plan, ordering)
        if result is None:
            continue
        ordering, forward, log_likelihood = result
        log_values.append(log_likelihood)
        messages.append(backward_ordering(plan, ordering, log_likelihood, forward))
    if not messages:
        raise ImpossibleEvidence('interval observation has zero path support')
    offset = max(log_values)
    log_likelihood = offset + sum((value - offset).exp() for value in log_values).ln()
    return messages, log_likelihood
