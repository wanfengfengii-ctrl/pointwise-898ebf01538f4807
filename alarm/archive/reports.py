import json
from dataclasses import dataclass
from decimal import Decimal
from uuid import uuid4


@dataclass(frozen=True)
class AnalysisReport:
    task_id: str
    payload: dict


class ReportNotFound(LookupError):
    pass


def assemble_report(task_id, snapshot, evidence, posteriors, occupancy):
    if posteriors.times != snapshot.queries or occupancy.axes != snapshot.axes:
        raise ValueError('report axes do not match frozen request')
    source = (snapshot.model.model_id, snapshot.model.revision,
              snapshot.observations.sequence_id, snapshot.observations.revision)
    if evidence.plan.source != source:
        raise ValueError('report source mismatch')
    payload = {
        'task_id': task_id,
        'binding': {'model_id': source[0], 'model_revision': source[1],
                    'sequence_id': source[2], 'observation_revision': source[3]},
        'T': snapshot.T, 'states': list(snapshot.model.definition.states),
        'alarms': [{'id': r.alarm_id, 'source_revision': r.source_revision,
                    'time': r.time, 'kind': r.kind} for r in snapshot.observations.records],
        'queries': [{'index': i, 'time': t} for i, t in enumerate(snapshot.queries)],
        'occupancy_axes': [{'index': a.index, 'state': a.state, 'start': a.start,
                            'end': a.end, 'label': a.label} for a in snapshot.axes],
        'log_likelihood': evidence.log_likelihood,
        'posteriors': [list(row) for row in posteriors.probabilities],
        'means': list(occupancy.means), 'covariance': [list(row) for row in occupancy.covariance]
    }
    return AnalysisReport(task_id, payload)


def _pack(value):
    if isinstance(value, Decimal):
        return {'$decimal': str(value)}
    if isinstance(value, dict):
        return {key: _pack(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_pack(item) for item in value]
    return value


def _unpack(value):
    if isinstance(value, dict):
        if set(value) == {'$decimal'}:
            return Decimal(value['$decimal'])
        return {key: _unpack(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_unpack(item) for item in value]
    return value


def encode_report(report):
    payload = report.payload if isinstance(report, AnalysisReport) else report
    return json.dumps(_pack(payload), ensure_ascii=False, separators=(',', ':'))


def decode_report(payload):
    return _unpack(json.loads(payload))


def publish_report(store, report, before_commit=None):
    with store.transaction() as db:
        old = db.execute('SELECT report_id FROM reports WHERE task_id=?', (report.task_id,)).fetchone()
        if old:
            return old[0]
        report_id = uuid4().hex
        db.execute('INSERT INTO reports VALUES (?,?,?)',
                   (report_id, report.task_id, encode_report(report)))
        changed = db.execute("UPDATE tasks SET status='PUBLISHED' WHERE task_id=? AND status='READY'",
                             (report.task_id,)).rowcount
        if changed != 1:
            raise ValueError('task is not publishable')
        if before_commit is not None:
            before_commit()
    return report_id


def read_report(store, report_id):
    row = store.connection.execute("SELECT r.payload FROM reports r JOIN tasks t ON t.task_id=r.task_id WHERE r.report_id=? AND t.status='PUBLISHED'",
                                   (report_id,)).fetchone()
    if row is None:
        raise ReportNotFound(report_id)
    return decode_report(row[0])
