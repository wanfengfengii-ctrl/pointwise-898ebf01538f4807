from decimal import Decimal
from alarm.archive.storage import ArchiveStore
from alarm.models.repository import register_model
from alarm.observations.batches import apply_observations
from alarm.archive.tasks import create_task
from alarm.archive.execution import analyze_task
from alarm.archive.reports import read_report

D = Decimal


def model(switch=False, rates=None):
    return {'states': ['idle', 'hot'],
            'Q': [[D('-0.7'), D('0.7')], [D('0.4'), D('-0.4')]] if switch else [[0, 0], [0, 0]],
            'initial': [D('0.5'), D('0.5')],
            'intensities': rates or {'a': [0, 2], 'b': [0, 0]}}


def prepare(store, definition=None, changes=()):
    receipt = register_model(store, 'device', 'initial', **(definition or model()))
    observations = apply_observations(store, 'stream', changes)
    return receipt, observations


def analyze(store, definition=None, changes=(), T=1, queries=(0, 1), windows=()):
    receipt, observations = prepare(store, definition, changes)
    task = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                       T, queries, windows)
    return read_report(store, analyze_task(store, task))


def put(identity, revision, time, kind='a'):
    return {'alarm_id': identity, 'source_revision': revision,
            'action': 'put', 'time': time, 'kind': kind}


def withdraw(identity, revision):
    return {'alarm_id': identity, 'source_revision': revision, 'action': 'withdraw'}


def window(state='hot', start=0, end=1, label=''):
    return {'state': state, 'start': start, 'end': end, 'label': label}


def close_decimal(test, actual, expected, tolerance=D('1e-8')):
    test.assertLessEqual(abs(actual - expected), tolerance, (actual, expected))
