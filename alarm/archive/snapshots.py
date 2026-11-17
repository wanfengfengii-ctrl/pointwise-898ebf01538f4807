import json
from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from alarm.models.types import ModelRevision, number, exact_precision
from alarm.models.repository import get_model_revision
from alarm.models.revisions import encode_model_definition, decode_model_definition
from alarm.observations.records import ObservationRevision
from alarm.observations.repository import read_observation_revision, source_payload, source_from_payload
from alarm.observations.revisions import order_active_records
from alarm.occupancy.requests import OccupancyAxis, validate_occupancy_requests


class SnapshotValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TaskSnapshot:
    model: ModelRevision
    observations: ObservationRevision
    T: Decimal
    queries: tuple
    axes: tuple


def freeze_task_inputs(store, model_id, model_revision, sequence_id, observation_revision,
                       T, queries=(), windows=()):
    model = get_model_revision(store, model_id, model_revision)
    observations = read_observation_revision(store, sequence_id, observation_revision)
    try:
        T = number(T)
        queries = tuple(number(t) for t in queries)
        if T < 0 or any(t < 0 or t > T for t in queries):
            raise ValueError('invalid horizon or query time')
        definition = model.definition
        kinds = {k for k, _ in definition.intensities}
        if len(observations.records) > 64:
            raise ValueError('at most 64 active alarms')
        if any(r.time > T or r.kind not in kinds for r in observations.records):
            raise ValueError('alarm outside horizon or unknown type')
        with localcontext() as ctx:
            ctx.prec = exact_precision(definition.numbers() + (T,))
            ctx.Emax = MAX_EMAX
            ctx.Emin = MIN_EMIN
            maximum = max(-definition.Q[i][i] + sum(row[i] for _, row in definition.intensities)
                          for i in range(len(definition.states)))
            if maximum * T > 40:
                raise ValueError('rate-horizon budget exceeds 40')
        axes = validate_occupancy_requests(definition, T, windows)
        return TaskSnapshot(model, observations, T, queries, axes)
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise SnapshotValidationError(str(exc)) from exc


def encode_task_snapshot(snapshot):
    return json.dumps({
        'model_id': snapshot.model.model_id, 'model_revision': snapshot.model.revision,
        'model': encode_model_definition(snapshot.model.definition),
        'sequence_id': snapshot.observations.sequence_id,
        'observation_revision': snapshot.observations.revision,
        'sources': [source_payload(v) for v in snapshot.observations.sources],
        'T': str(snapshot.T), 'queries': [str(t) for t in snapshot.queries],
        'axes': [[a.index, a.state, str(a.start), str(a.end), a.label] for a in snapshot.axes]
    }, ensure_ascii=False, separators=(',', ':'))


def decode_task_snapshot(payload):
    value = json.loads(payload)
    model = ModelRevision(value['model_id'], value['model_revision'],
                          decode_model_definition(value['model']))
    sources = tuple(source_from_payload(v) for v in value['sources'])
    observations = ObservationRevision(value['sequence_id'], value['observation_revision'],
                                       sources, order_active_records(sources))
    axes = tuple(OccupancyAxis(i, state, Decimal(a), Decimal(b), label)
                 for i, state, a, b, label in value['axes'])
    return TaskSnapshot(model, observations, Decimal(value['T']),
                        tuple(Decimal(t) for t in value['queries']), axes)
