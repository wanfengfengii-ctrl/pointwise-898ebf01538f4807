from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class EvidenceInterval:
    start: Decimal
    end: Decimal


@dataclass(frozen=True)
class EvidenceEvent:
    time: Decimal
    alarm_id: str
    source_revision: int
    kind: str


@dataclass(frozen=True)
class EvidencePlan:
    model: object
    T: Decimal
    events: tuple
    steps: tuple
    source: tuple


def split_evidence_intervals(plan, boundaries=()):
    cuts = {Decimal(0), plan.T}
    cuts.update(event.time for event in plan.events)
    cuts.update(boundaries)
    if any(t < 0 or t > plan.T for t in cuts):
        raise ValueError('split outside observation interval')
    events = {}
    for event in plan.events:
        events.setdefault(event.time, []).append(event)
    steps = []
    previous = Decimal(0)
    for time in sorted(cuts):
        if time > previous:
            steps.append(EvidenceInterval(previous, time))
        steps.extend(events.get(time, ()))
        previous = time
    return tuple(steps)


def build_evidence_plan(snapshot):
    events = tuple(EvidenceEvent(r.time, r.alarm_id, r.source_revision, r.kind)
                   for r in snapshot.observations.records)
    if any(e.time < 0 or e.time > snapshot.T for e in events):
        raise ValueError('snapshot contains out-of-range event')
    source = (snapshot.model.model_id, snapshot.model.revision,
              snapshot.observations.sequence_id, snapshot.observations.revision)
    draft = EvidencePlan(snapshot.model.definition, snapshot.T, events, (), source)
    return EvidencePlan(draft.model, draft.T, draft.events,
                        split_evidence_intervals(draft), source)
