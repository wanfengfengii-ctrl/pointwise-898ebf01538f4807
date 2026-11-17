import unittest
from decimal import Decimal, localcontext
from alarm.archive.storage import ArchiveStore
from alarm.archive.tasks import create_task, load_task_snapshot
from alarm.archive.execution import analyze_task
from alarm.archive.reports import read_report
from alarm.archive.snapshots import SnapshotValidationError
from alarm.models.repository import ModelRevisionNotFound
from alarm.evidence.propagation import ImpossibleEvidence
from tests.support import D, model, prepare, analyze, put, window, close_decimal


class EvidenceTests(unittest.TestCase):
    def test_silence_changes_posterior(self):
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 70
            result = analyze(store, windows=[window()])
            p = D(-2).exp() / (1 + D(-2).exp())
            close_decimal(self, result['log_likelihood'], ((1 + D(-2).exp()) / 2).ln())
            for row in result['posteriors']:
                close_decimal(self, row[1], p)
            close_decimal(self, result['means'][0], p)
            close_decimal(self, result['covariance'][0][0], p * (1 - p))

    def test_coincident_marks(self):
        value = model(rates={'a': [1, 3], 'b': [2, 1]})
        changes = [put('x', 1, D('0.5')), put('y', 1, D('0.5')),
                   put('z', 1, D('0.5'), 'b')]
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 70
            result = analyze(store, value, changes, queries=[0, D('0.5'), 1])
            low = D(-3).exp() * 2
            high = D(-4).exp() * 9
            p = high / (low + high)
            self.assertEqual(len(result['alarms']), 3)
            close_decimal(self, result['log_likelihood'], ((low + high) / 2).ln())
            for row in result['posteriors']:
                close_decimal(self, row[1], p)

    def test_impossible_mark(self):
        with ArchiveStore.open() as store:
            receipt, observations = prepare(store, changes=[put('bad', 1, D('0.5'), 'b')])
            task = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                               1, [0], [window()])
            for _ in range(2):
                with self.assertRaises(ImpossibleEvidence):
                    analyze_task(store, task)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM reports').fetchone()[0], 0)
            self.assertEqual(store.connection.execute('SELECT status FROM tasks').fetchone()[0], 'READY')

    def test_future_mark_and_tail(self):
        value = model(rates={'a': [1, 3], 'b': [0, 0]})
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 70
            receipt, observations = prepare(store, value, [put('future', 1, D('0.75'))])
            task = create_task(store, 'device', 1, 'stream', observations.revision, 1,
                               [0, D('0.75'), 1], [])
            result = read_report(store, analyze_task(store, task))
            p = 3 * D(-3).exp() / (D(-1).exp() + 3 * D(-3).exp())
            for row in result['posteriors']:
                close_decimal(self, row[1], p)
            shorter = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                                  D('0.75'), [0], [])
            short = read_report(store, analyze_task(store, shorter))
            self.assertGreater(short['posteriors'][0][1], p)

    def test_positive_rare_evidence(self):
        value = model(rates={'a': [D('1e-300'), D('2e-300')], 'b': [0, 0]})
        changes = [put(str(i), 1, D(i) / 64) for i in range(64)]
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 80
            result = analyze(store, value, changes, windows=[window()])
            low = (-D('1e-300')).exp()
            high = D(2) ** 64 * (-D('2e-300')).exp()
            p = high / (low + high)
            expected_log = 64 * D('1e-300').ln() + ((low + high) / 2).ln()
            self.assertTrue(result['log_likelihood'].is_finite())
            close_decimal(self, result['log_likelihood'], expected_log)
            close_decimal(self, result['means'][0], p)

    def test_partition_and_endpoints(self):
        value = model(rates={'a': [1, 2], 'b': [2, 1]})
        with ArchiveStore.open() as store:
            receipt, observations = prepare(store, value, [put('begin', 1, 0), put('end', 1, 1, 'b')])
            first = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                                1, [D('0.5')], [window()])
            second = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                                 1, [D('0.7'), D('0.5'), D('0.1')],
                                 [window(end=D('0.3')), window(start=D('0.3'))])
            a, b = [read_report(store, analyze_task(store, t)) for t in (first, second)]
            close_decimal(self, a['log_likelihood'], b['log_likelihood'])
            self.assertEqual(a['posteriors'][0], b['posteriors'][1])
            close_decimal(self, a['means'][0], sum(b['means']))
            close_decimal(self, a['covariance'][0][0], sum(sum(row) for row in b['covariance']))
            close_decimal(self, a['posteriors'][0][1], D('0.5'))

    def test_snapshot_bounds_and_input_copy(self):
        with ArchiveStore.open() as store:
            receipt, observations = prepare(store)
            def count():
                return store.connection.execute('SELECT COUNT(*) FROM tasks').fetchone()[0]
            with self.assertRaises(ModelRevisionNotFound):
                create_task(store, 'device', 99, 'stream', 1, 1)
            cases = [(-1, [], []), (1, [2], []),
                     (1, [], [window(state='missing')]),
                     (1, [], [window(start=D('0.9'), end=D('0.1'))]),
                     (21, [], []), (1, [], [window()] * 5)]
            for T, queries, windows in cases:
                with self.subTest(T=T, queries=queries, windows=windows), self.assertRaises(SnapshotValidationError):
                    create_task(store, 'device', 1, 'stream', 1, T, queries, windows)
            self.assertEqual(count(), 0)
            queries, windows = [1, 0], [window(), window()]
            task = create_task(store, 'device', receipt.revision, 'stream', observations.revision,
                               1, queries, windows)
            queries.reverse()
            windows[0]['state'] = 'missing'
            snapshot = load_task_snapshot(store, task)
            self.assertEqual(snapshot.queries, (D(1), D(0)))
            self.assertEqual(len(snapshot.axes), 2)
            bad = prepare
            del bad
            newer = __import__('alarm.observations.batches', fromlist=['apply_observations']).apply_observations
            unknown = newer(store, 'unknown', [put('x', 1, 0, 'unknown')])
            with self.assertRaises(SnapshotValidationError):
                create_task(store, 'device', 1, 'unknown', unknown.revision, 1)
            outside = newer(store, 'outside', [put('x', 1, 2)])
            with self.assertRaises(SnapshotValidationError):
                create_task(store, 'device', 1, 'outside', outside.revision, 1)


class OccupancyTests(unittest.TestCase):
    def test_disjoint_windows_share_state(self):
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 70
            result = analyze(store, T=2, queries=[0, 2],
                             windows=[window(end=1), window(start=1, end=2)])
            p = D(-4).exp() / (1 + D(-4).exp())
            for mean in result['means']:
                close_decimal(self, mean, p)
            for row in result['covariance']:
                for covariance in row:
                    close_decimal(self, covariance, p * (1 - p))

    def test_overlap_duplicates_and_zero_window(self):
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 70
            lengths = [D('0.75'), D(1), D(1), D(0)]
            result = analyze(store, windows=[window(end=D('0.75'), label='part'),
                                            window(label='first'), window(label='duplicate'),
                                            window(start=D('0.3'), end=D('0.3'), label='empty')])
            p = D(-2).exp() / (1 + D(-2).exp())
            self.assertEqual([a['index'] for a in result['occupancy_axes']], list(range(4)))
            for i in range(4):
                close_decimal(self, result['means'][i], lengths[i] * p)
                for j in range(4):
                    close_decimal(self, result['covariance'][i][j], lengths[i] * lengths[j] * p * (1 - p))
            self.assertEqual(result['covariance'][3], [D(0)] * 4)

    def test_zero_horizon_and_reachable_support(self):
        with ArchiveStore.open() as store:
            result = analyze(store, model(rates={'a': [1, 2], 'b': [0, 0]}),
                             [put('x', 1, 0)], T=0, queries=[0], windows=[window(end=0)])
            close_decimal(self, result['posteriors'][0][1], D(2) / 3)
            self.assertEqual(result['means'], [D(0)])
            self.assertEqual(result['covariance'], [[D(0)]])
        value = model(True)
        value['initial'] = [1, 0]
        with ArchiveStore.open() as store:
            result = analyze(store, value, [put('later', 1, D('0.5'))], windows=[window()])
            self.assertGreater(result['means'][0], 0)
        with ArchiveStore.open() as store:
            receipt, observations = prepare(store, value, [put('now', 1, 0)])
            task = create_task(store, 'device', receipt.revision, 'stream', observations.revision, 1)
            with self.assertRaises(ImpossibleEvidence):
                analyze_task(store, task)

    def test_large_horizon_absolute_precision(self):
        T = D('1e30')
        value = model(rates={'a': [0, D('2e-30')], 'b': [0, 0]})
        with ArchiveStore.open() as store, localcontext() as ctx:
            ctx.prec = 160
            result = analyze(store, value, T=T, queries=[0, T], windows=[window(end=T)])
            p = D(-2).exp() / (1 + D(-2).exp())
            close_decimal(self, result['means'][0], T * p)
            close_decimal(self, result['covariance'][0][0], T * T * p * (1 - p))
