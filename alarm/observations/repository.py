import json
from decimal import Decimal
from alarm.models.types import decimal_text
from alarm.observations.records import SourceVersion, ObservationRevision
from alarm.observations.revisions import order_active_records


class ObservationRevisionNotFound(LookupError):
    pass


def source_payload(value):
    return [value.alarm_id, value.source_revision, value.action,
            None if value.time is None else decimal_text(value.time), value.kind]


def source_from_payload(value):
    identity, revision, action, time, kind = value
    return SourceVersion(identity, revision, action,
                         None if time is None else Decimal(time), kind)


def read_observation_revision(store, sequence_id, revision=None):
    if revision is None:
        row = store.connection.execute('SELECT revision,payload FROM observation_revisions WHERE sequence_id=? ORDER BY revision DESC LIMIT 1',
                                       (sequence_id,)).fetchone()
    else:
        if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
            raise ObservationRevisionNotFound((sequence_id, revision))
        row = store.connection.execute('SELECT revision,payload FROM observation_revisions WHERE sequence_id=? AND revision=?',
                                       (sequence_id, revision)).fetchone()
    if row is None:
        raise ObservationRevisionNotFound((sequence_id, revision))
    sources = tuple(source_from_payload(v) for v in json.loads(row[1]))
    return ObservationRevision(sequence_id, row[0], sources, order_active_records(sources))


def read_source_history(store, sequence_id):
    rows = store.connection.execute('SELECT payload FROM source_history WHERE sequence_id=? ORDER BY alarm_id,source_revision',
                                    (sequence_id,))
    return tuple(source_from_payload(json.loads(row[0])) for row in rows)


def persist_observation_revision(store, sequence_id, revision, merge, write_revision):
    db = store.connection
    if not db.in_transaction:
        raise RuntimeError('observation persistence requires a transaction')
    for value in merge.history:
        db.execute('INSERT OR IGNORE INTO source_history VALUES (?,?,?,?)',
                   (sequence_id, value.alarm_id, value.source_revision,
                    json.dumps(source_payload(value), ensure_ascii=False)))
    if write_revision:
        payload = json.dumps([source_payload(v) for v in merge.sources], ensure_ascii=False)
        db.execute('INSERT INTO observation_revisions VALUES (?,?,?)',
                   (sequence_id, revision, payload))
