from dataclasses import dataclass
from alarm.observations.validation import ObservationRevisionConflict


@dataclass(frozen=True)
class ObservationMerge:
    sources: tuple
    records: tuple
    history: tuple
    changed: bool


def order_active_records(sources):
    records = (source.active_record() for source in sources)
    # Display order only: location start (exact time or interval lo), then identity.
    # This ordering does not claim anything about actual event occurrence order.
    return tuple(sorted((r for r in records if r is not None),
                        key=lambda r: (r.location, r.alarm_id)))


def merge_observations(current, history, incoming):
    known = {(v.alarm_id, v.source_revision): v for v in history}
    for value in incoming:
        key = value.alarm_id, value.source_revision
        if key in known and known[key].content() != value.content():
            raise ObservationRevisionConflict(key)
    latest = {v.alarm_id: v for v in current}
    for value in incoming:
        known[value.alarm_id, value.source_revision] = value
        old = latest.get(value.alarm_id)
        if old is None or value.source_revision > old.source_revision:
            latest[value.alarm_id] = value
    sources = tuple(latest[key] for key in sorted(latest))
    return ObservationMerge(sources, order_active_records(sources),
                            tuple(known[key] for key in sorted(known)),
                            sources != tuple(current))
