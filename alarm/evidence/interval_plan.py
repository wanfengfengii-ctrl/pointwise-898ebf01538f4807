"""Timeline material for interval-marked observations.

An interval identity is a single marked point event whose time is only known to
lie inside ``[lo, hi]``.  The horizon is cut into elementary pieces at exact
event times, interval endpoints, query times and occupancy window boundaries.
Inside every piece the set of interval identities that may be placed there is
constant, so each fixed identity ordering is propagated with one block-upper
triangular matrix exponential per piece (the standard integral block trick).
"""
from dataclasses import dataclass
from decimal import Decimal
from alarm.evidence.timeline import EvidenceEvent


@dataclass(frozen=True)
class IntervalMark:
    alarm_id: str
    source_revision: int
    kind: str
    lo: Decimal
    hi: Decimal


@dataclass(frozen=True)
class Piece:
    start: Decimal
    end: Decimal
    active: tuple  # tuple of interval indices whose [lo, hi] covers the piece


@dataclass(frozen=True)
class CoincidentMarks:
    time: Decimal
    events: tuple


@dataclass(frozen=True)
class IntervalPlan:
    model: object
    T: Decimal
    exact_events: tuple
    interval_marks: tuple
    cuts: tuple
    pieces: tuple
    mark_cuts: tuple
    orderings: tuple
    queries: tuple
    source: tuple


def build_interval_plan(snapshot, queries, axes):
    model = snapshot.model.definition
    records = snapshot.observations.records
    exact_events = tuple(EvidenceEvent(r.time, r.alarm_id, r.source_revision, r.kind)
                         for r in records if not r.is_interval)
    interval_marks = tuple(
        IntervalMark(r.alarm_id, r.source_revision, r.kind, r.interval[0], r.interval[1])
        for r in records if r.is_interval)
    cuts = {Decimal(0), snapshot.T}
    cuts.update(event.time for event in exact_events)
    cuts.update(boundary for mark in interval_marks for boundary in (mark.lo, mark.hi))
    cuts.update(queries)
    cuts.update(boundary for axis in axes for boundary in (axis.start, axis.end))
    cuts = tuple(sorted(cuts))
    pieces = []
    for start, end in zip(cuts, cuts[1:]):
        if end <= start:
            continue
        active = tuple(index for index, mark in enumerate(interval_marks)
                       if mark.lo <= start and end <= mark.hi)
        pieces.append(Piece(start, end, active))
    grouped = {}
    for event in exact_events:
        grouped.setdefault(event.time, []).append(event)
    mark_cuts = tuple(CoincidentMarks(time, tuple(grouped[time]))
                      for time in sorted(grouped))
    orderings = _permutations(tuple(range(len(interval_marks))))
    source = (snapshot.model.model_id, snapshot.model.revision,
              snapshot.observations.sequence_id, snapshot.observations.revision)
    return IntervalPlan(model, snapshot.T, exact_events, interval_marks, cuts,
                        tuple(pieces), mark_cuts, tuple(orderings), tuple(queries), source)


def _permutations(values):
    if len(values) <= 1:
        return [values]
    result = []
    for index, value in enumerate(values):
        rest = values[:index] + values[index + 1:]
        result.extend((value,) + tail for tail in _permutations(rest))
    return result


def interval_has_support(plan, ordering):
    """Structural, threshold-free zero-support check for one identity ordering.

    A state in completion stage ``s`` is reachable when it can be reached by
    state transitions through silence and, whenever the next ordering
    identity is placeable, by taking that identity's positive mark rate.
    Exact alarms filter the reachable states of every stage.
    """
    model = plan.model
    n = len(model.states)
    stages = len(ordering) + 1
    reachable = [set() for _ in range(stages)]
    reachable[0] = {i for i, probability in enumerate(model.initial) if probability > 0}
    piece_iter = iter(plan.pieces)
    mark_iter = iter(plan.mark_cuts)
    piece = next(piece_iter, None)
    marks = next(mark_iter, None)

    while piece is not None or marks is not None:
        next_piece = piece.end if piece is not None else None
        next_mark = marks.time if marks is not None else None
        if next_mark is not None and (next_piece is None or next_mark <= next_piece):
            for event in marks.events:
                rates = model.rates(event.kind)
                reachable = [{i for i in block if rates[i] > 0} for block in reachable]
            if not any(reachable):
                return False
            marks = next(mark_iter, None)
            continue
        # Inside a piece, silence (Q closure) and each placeable mark can act
        # repeatedly until no new stage/state pair becomes reachable.
        changed = True
        while changed:
            changed = False
            for stage in range(stages):
                pending = list(reachable[stage])
                while pending:
                    state = pending.pop()
                    for target, rate in enumerate(model.Q[state]):
                        if state != target and rate > 0 and target not in reachable[stage]:
                            reachable[stage].add(target)
                            pending.append(target)
                            changed = True
            for stage, identity in enumerate(ordering):
                if identity not in piece.active:
                    continue
                rates = model.rates(plan.interval_marks[identity].kind)
                for state in reachable[stage]:
                    if rates[state] > 0 and state not in reachable[stage + 1]:
                        reachable[stage + 1].add(state)
                        changed = True
        piece = next(piece_iter, None)
    return bool(reachable[len(ordering)])
