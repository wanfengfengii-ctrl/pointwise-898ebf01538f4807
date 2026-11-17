from alarm.models.types import identifier
from alarm.observations.validation import validate_observation_batch
from alarm.observations.revisions import merge_observations
from alarm.observations.repository import (
    ObservationRevisionNotFound, read_observation_revision,
    read_source_history, persist_observation_revision)


def apply_observations(store, sequence_id, changes):
    identifier(sequence_id)
    incoming = validate_observation_batch(changes)
    with store.transaction():
        try:
            current = read_observation_revision(store, sequence_id)
        except ObservationRevisionNotFound:
            current = None
        sources = () if current is None else current.sources
        history = read_source_history(store, sequence_id)
        merge = merge_observations(sources, history, incoming)
        write = current is None or merge.changed
        revision = 1 if current is None else current.revision + int(merge.changed)
        persist_observation_revision(store, sequence_id, revision, merge, write)
    return read_observation_revision(store, sequence_id, revision)
