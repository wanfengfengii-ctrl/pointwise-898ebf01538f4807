import tempfile
import unittest
from pathlib import Path
from alarm.archive.storage import ArchiveStore
from alarm.models.repository import register_model, get_model_revision
from alarm.observations.batches import apply_observations
from alarm.observations.repository import read_source_history
from alarm.archive.tasks import create_task
from alarm.archive.execution import analyze_task
from alarm.archive.reports import read_report, ReportNotFound
from tests.support import D, model, prepare, put, withdraw, window, close_decimal


class ArchiveTests(unittest.TestCase):
    def test_frozen_task_after_correction(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.sqlite'
            store = ArchiveStore.open(path)
            receipt, observations = prepare(store, model(True), [put('a', 1, D('0.3'))])
            axes = [window(start=D('0.6'), label='B'), window(end=D('0.6'), label='A'),
                    window(end=D('0.6'), label='A duplicate')]
            old = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                              1, [1, 0, D('0.3')], axes)
            control = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                                  1, [1, 0, D('0.3')], axes)
            expected = read_report(store, analyze_task(store, control))
            revised = model(True, {'a': [2, 1], 'b': [0, 1]})
            register_model(store, 'device', 'replacement', **revised)
            new_observations = apply_observations(store, 'stream', [withdraw('a', 2), put('b', 1, D('0.8'), 'b')])
            new = create_task(store, 'device', 2, 'stream', new_observations.revision, 1,
                              [1, 0, D('0.3')], axes)
            store.close()
            store = ArchiveStore.open(path)
            try:
                old_id = analyze_task(store, old)
                result = read_report(store, old_id)
                for field in ['binding', 'states', 'alarms', 'queries', 'occupancy_axes',
                              'log_likelihood', 'posteriors', 'means', 'covariance']:
                    self.assertEqual(result[field], expected[field])
                changed = read_report(store, analyze_task(store, new))
                self.assertEqual(changed['binding']['model_revision'], 2)
                self.assertNotEqual(changed['log_likelihood'], result['log_likelihood'])
                self.assertEqual([a['label'] for a in result['occupancy_axes']], ['B', 'A', 'A duplicate'])
                self.assertEqual(result['means'][1], result['means'][2])
                close_decimal(self, result['covariance'][1][1], result['covariance'][1][2])
                result['means'][0] = D(-100)
                result['covariance'][0][0] = D(-100)
                result['queries'].clear()
                again = read_report(store, old_id)
                self.assertEqual(again['means'], expected['means'])
                self.assertEqual(again['queries'], expected['queries'])
                self.assertEqual(get_model_revision(store, 'device', 1).definition.rates('a'), (0, 2))
            finally:
                store.close()

    def test_publish_rollback_and_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.sqlite'
            store = ArchiveStore.open(path)
            receipt, observations = prepare(store)
            old = create_task(store, 'device', receipt.revision, 'stream', observations.revision, 1, [0], [window()])
            old_id = analyze_task(store, old)
            old_report = read_report(store, old_id)
            pending = create_task(store, 'device', 1, 'stream', 1, 1, [1], [window()])
            def fail():
                raise RuntimeError('publication interrupted')
            with self.assertRaisesRegex(RuntimeError, 'publication interrupted'):
                analyze_task(store, pending, before_commit=fail)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 1)
            store.close()
            store = ArchiveStore.open(path)
            try:
                self.assertEqual(read_report(store, old_id), old_report)
                self.assertEqual(store.connection.execute('SELECT status FROM tasks WHERE task_id=?', (pending,)).fetchone()[0], 'READY')
                self.assertEqual(register_model(store, 'device', 'initial', **model()).revision, 1)
                new_id = analyze_task(store, pending)
                self.assertEqual(analyze_task(store, pending, before_commit=fail), new_id)
                self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 2)
                with self.assertRaises(ReportNotFound):
                    read_report(store, 'missing')
            finally:
                store.close()

    def test_source_history_survives_reopen_and_conflict(self):
        from alarm.observations.validation import ObservationRevisionConflict
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.sqlite'
            with ArchiveStore.open(path) as store:
                prepare(store, changes=[put('x', 1, 0)])
                apply_observations(store, 'stream', [withdraw('x', 3)])
                before = read_source_history(store, 'stream')
                with self.assertRaises(ObservationRevisionConflict):
                    apply_observations(store, 'stream', [put('valid', 1, 0), put('x', 1, 1)])
            with ArchiveStore.open(path) as store:
                self.assertEqual(read_source_history(store, 'stream'), before)
                revision = apply_observations(store, 'stream', [put('x', 2, 0)])
                self.assertEqual(revision.records, ())
                self.assertEqual(revision.sources[0].source_revision, 3)
