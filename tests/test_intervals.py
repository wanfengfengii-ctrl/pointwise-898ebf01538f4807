import unittest
from decimal import Decimal as D, localcontext
from alarm.archive.storage import ArchiveStore
from alarm.models.repository import register_model
from alarm.observations.batches import apply_observations
from alarm.observations.validation import (
    ObservationValidationError, ObservationRevisionConflict)
from alarm.archive.tasks import create_task
from alarm.archive.execution import analyze_task
from alarm.archive.reports import read_report, encode_report, decode_report
from alarm.archive.snapshots import SnapshotValidationError
from alarm.evidence.propagation import ImpossibleEvidence
from examples.interval_cases import cases, assert_expected
from tests.interval_audit import static_analytic, nested_grid


def register(store, definition, model_id='m'):
    return register_model(store, model_id, 'r', **definition)


def interval_change(identity, lo, hi, kind='a', revision=1):
    return {'alarm_id': identity, 'source_revision': revision, 'action': 'put',
            'interval': [D(str(lo)), D(str(hi))], 'kind': kind}


def exact_change(identity, time, kind='a', revision=1):
    return {'alarm_id': identity, 'source_revision': revision, 'action': 'put',
            'time': D(time), 'kind': kind}


def _static_definition():
    return {'states': ['idle', 'hot'], 'Q': [[0, 0], [0, 0]],
            'initial': [D('.4'), D('.6')],
            'intensities': {'a': [1, 2], 'b': [D('.5'), D('.25')]}}


class IntervalObservationTests(unittest.TestCase):
    def test_time_or_interval_exclusive_and_shapes(self):
        with ArchiveStore.open() as store:
            register(store, _static_definition())
            bad = [
                {**exact_change('x', '.5'), 'interval': [D(0), D(1)]},
                {'alarm_id': 'x', 'source_revision': 1, 'action': 'put', 'kind': 'a'},
                interval_change('x', 1, 1), interval_change('x', 2, 1),
                interval_change('x', -.1, 1), interval_change('x', 0, 0),
                interval_change('x', 0, 1, kind=''),
                {'alarm_id': 'x', 'source_revision': 1, 'action': 'put',
                 'interval': [D(0)], 'kind': 'a'},
                {'alarm_id': 'x', 'source_revision': 1, 'action': 'put',
                 'interval': '01', 'kind': 'a'}]
            for change in bad:
                with self.subTest(change=change):
                    with self.assertRaises(ObservationValidationError):
                        apply_observations(store, 's', [change])
            with self.assertRaises(ObservationValidationError):
                apply_observations(store, 's', [
                    {'alarm_id': 'x', 'source_revision': 1,
                     'action': 'withdraw', 'interval': [D(0), D(1)]}])

    def test_content_equality_alias_and_correction(self):
        with ArchiveStore.open() as store:
            register(store, _static_definition())
            mutable = [D(0), D(1)]
            first = apply_observations(store, 's', [interval_change('x', 0, 1)])
            replay = apply_observations(
                store, 's', [{'alarm_id': 'x', 'source_revision': 1,
                              'action': 'put', 'interval': (D(0), D(1)), 'kind': 'a'}])
            self.assertEqual(first, replay)
            mutable[0] = D(99)
            self.assertEqual(read(store), (D(0), D(1)))
            corrected = apply_observations(store, 's', [exact_change('x', '.5', revision=2)])
            self.assertEqual(corrected.records[0].time, D('.5'))
            self.assertIsNone(corrected.records[0].interval)
            back = apply_observations(store, 's', [interval_change('x', '.1', '.9', revision=3)])
            self.assertEqual(back.records[0].interval, (D('.1'), D('.9')))
            self.assertIsNone(back.records[0].time)

    def test_history_conflict_includes_interval_content(self):
        with ArchiveStore.open() as store:
            register(store, _static_definition())
            apply_observations(store, 's', [interval_change('x', 0, 1)])
            with self.assertRaises(ObservationRevisionConflict):
                apply_observations(store, 's', [interval_change('x', 0, '.5')])
            with self.assertRaises(ObservationRevisionConflict):
                apply_observations(store, 's', [exact_change('x', '.5')])


def read(store):
    from alarm.observations.repository import read_observation_revision
    revision = read_observation_revision(store, 's')
    return revision.records[0].interval


class IntervalTaskLimitTests(unittest.TestCase):
    def test_interval_task_caps(self):
        with ArchiveStore.open() as store:
            receipt = register(store, _static_definition())
            three = apply_observations(
                store, 'three', [interval_change('i%d' % k, 0, 1) for k in range(3)])
            with self.assertRaises(SnapshotValidationError):
                create_task(store, 'm', receipt.revision, 'three', three.revision, 1)
            many_exact = apply_observations(store, 'exact', [
                interval_change('iv', 0, 1)] + [
                exact_change('e%d' % k, k / 10) for k in range(9)])
            with self.assertRaises(SnapshotValidationError):
                create_task(store, 'm', receipt.revision, 'exact', many_exact.revision, 1)
            two = apply_observations(store, 'win', [interval_change('iv', 0, 1)])
            window = {'state': 'idle', 'start': D(0), 'end': D(1), 'label': 'w'}
            with self.assertRaises(SnapshotValidationError):
                create_task(store, 'm', receipt.revision, 'win', two.revision, 1,
                            windows=[window] * 3)
            beyond = apply_observations(store, 'beyond', [interval_change('iv', 0, 2)])
            with self.assertRaises(SnapshotValidationError):
                create_task(store, 'm', receipt.revision, 'beyond', beyond.revision, 1)

    def test_pure_exact_task_keeps_full_capacity(self):
        with ArchiveStore.open() as store:
            receipt = register(store, _static_definition())
            changes = [exact_change('e%d' % k, k / 64) for k in range(32)]
            observations = apply_observations(store, 'stream', changes)
            task = create_task(store, 'm', receipt.revision, 'stream',
                               observations.revision, 1, windows=[
                                   {'state': 'idle', 'start': D(0), 'end': D(1)}] * 4)
            report = read_report(store, analyze_task(store, task))
            self.assertEqual(len(report['alarms']), 32)


class IntervalAnalysisTests(unittest.TestCase):
    def test_public_analytic_cases(self):
        for name in ('switch', 'static', 'rare'):
            with self.subTest(name=name), localcontext() as ctx:
                ctx.prec = 90
                case = cases()[name]
                with ArchiveStore.open() as store:
                    receipt = register(store, case['definition'])
                    observations = apply_observations(store, 's', case['changes'])
                    task = create_task(store, 'm', receipt.revision, 's',
                                       observations.revision, case['T'],
                                       case['queries'], case['windows'])
                    assert_expected(read_report(store, analyze_task(store, task)), name)

    def test_overlapping_nested_and_disjoint_intervals_against_audit(self):
        from tests.interval_audit import static_analytic
        definition = {'states': ['idle', 'hot'], 'Q': [[0, 0], [0, 0]],
                      'initial': [D('.4'), D('.6')],
                      'intensities': {'a': [1, 2], 'b': [D('.5'), D('.25')]}}
        windows = [{'state': 'idle', 'start': D(0), 'end': D('.7'), 'label': 'i'},
                   {'state': 'hot', 'start': D('.2'), 'end': D(1), 'label': 'h'}]
        audit_windows = [('idle', D(0), D('.7')), ('hot', D('.2'), D(1))]
        scenarios = {
            'overlap': ((0, 1), (0, 1)),
            'nested': ((0, 1), ('.25', '.75')),
            'disjoint': ((0, '.4'), ('.6', 1))}
        for label, (first_bounds, second_bounds) in scenarios.items():
            with self.subTest(label=label), localcontext() as ctx:
                ctx.prec = 80
                changes = [interval_change('first', *first_bounds, kind='a'),
                           interval_change('second', *second_bounds, kind='a')]
                report = _run(definition, changes, windows)
                reference = static_analytic(
                    definition,
                    [(D(str(first_bounds[0])), D(str(first_bounds[1])), 'a'),
                     (D(str(second_bounds[0])), D(str(second_bounds[1])), 'a')],
                    1, audit_windows)
                self.assertLess(abs(report['log_likelihood'] - reference['log_likelihood']),
                                D('1e-8'), label)
                for i in range(2):
                    self.assertLess(abs(report['means'][i] - reference['means'][i]),
                                    D('1e-8'), label)
                    for j in range(2):
                        self.assertLess(
                            abs(report['covariance'][i][j] - reference['covariance'][i][j]),
                            D('1e-8'), label)

    def test_switching_model_against_independent_nested_grid(self):
        from tests.interval_audit import nested_grid
        definition = {'states': ['idle', 'hot'],
                      'Q': [[D('-.4'), D('.4')], [D('.3'), D('-.3')]],
                      'initial': [D(1), D(0)],
                      'intensities': {'a': [1, 2], 'b': [D('.5'), D('.25')]}}
        windows = [{'state': 'hot', 'start': D(0), 'end': D('.5'), 'label': 'e'},
                   {'state': 'hot', 'start': D('.5'), 'end': D(1), 'label': 'l'}]
        with localcontext() as ctx:
            ctx.prec = 70
            changes = [interval_change('lo', 0, '.8', 'a'),
                       interval_change('hi', '.2', 1, 'b')]
            report = _run(definition, changes, windows)
            # The independent grid is first-order; refining it must converge to
            # the production value, which is the convergence target.
            previous = None
            for grid in (24, 48):
                reference = nested_grid(
                    definition,
                    [(D(0), D('.8'), 'a'), (D('.2'), D(1), 'b')], [], 1,
                    [('hot', D(0), D('.5')), ('hot', D('.5'), D(1))], grid=grid)
                gap = abs(report['log_likelihood'] - reference['log_likelihood'])
                if previous is not None:
                    self.assertLess(gap, previous)
                previous = gap
            self.assertLess(previous, D('0.02'))

    def test_exact_alarm_sandwiched_inside_intervals(self):
        definition = {'states': ['idle', 'hot'],
                      'Q': [[D('-.5'), D('.5')], [D('.3'), D('-.3')]],
                      'initial': [D(1), D(0)],
                      'intensities': {'a': [1, 2], 'b': [D('.5'), D('.25')]}}
        with localcontext() as ctx:
            ctx.prec = 80
            changes = [interval_change('lo', 0, '.6', 'a'),
                       interval_change('hi', '.4', 1, 'b'),
                       exact_change('pin', '.5', 'b')]
            with ArchiveStore.open() as store:
                receipt = register(store, definition)
                observations = apply_observations(store, 'stream', changes)
                task = create_task(store, 'm', receipt.revision, 'stream',
                                   observations.revision, 1, [D(0), D('.5'), D(1)],
                                   [{'state': 'hot', 'start': D(0), 'end': D(1)}])
                report = read_report(store, analyze_task(store, task))
            for row in report['posteriors']:
                self.assertLess(abs(sum(row) - 1), D('1e-30'))
                self.assertTrue(all(0 <= value <= 1 for value in row))
            self.assertTrue(all(value.is_finite() for value in report['means']))

    def test_structural_zero_and_tiny_positive_evidence(self):
        zero_model = {'states': ['idle', 'hot'], 'Q': [[0, 0], [0, 0]],
                      'initial': [1, 0],
                      'intensities': {'a': [1, 0], 'b': [0, 0]}}
        with ArchiveStore.open() as store:
            observations = apply_observations(
                store, 'zero', [interval_change('z', '.1', '.9', 'b')])
            receipt = register(store, zero_model, 'zero-model')
            task = create_task(store, 'zero-model', receipt.revision, 'zero',
                               observations.revision, 1)
            with self.assertRaises(ImpossibleEvidence):
                analyze_task(store, task)
            self.assertEqual(
                store.connection.execute("SELECT status FROM tasks").fetchone()[0], 'READY')
        tiny_model = {'states': ['idle', 'hot'], 'Q': [[0, 0], [0, 0]],
                      'initial': [D('.4'), D('.6')],
                      'intensities': {'a': [D('1e-300'), D('2e-300')], 'b': [0, 0]}}
        with ArchiveStore.open() as store:
            # Same geometry and priors as the public rare analytic case:
            # widths .5 and .75, priors .4/.6, so the hot posterior is 6/7.
            observations = apply_observations(
                store, 'tiny', [interval_change('t1', 0, '.5'),
                                interval_change('t2', '.25', 1)])
            receipt = register(store, tiny_model, 'tiny-model')
            task = create_task(store, 'tiny-model', receipt.revision, 'tiny',
                               observations.revision, 1, [D(1)])
            report = read_report(store, analyze_task(store, task))
            self.assertTrue(report['log_likelihood'].is_finite())
            self.assertLess(report['log_likelihood'], D(-1300))
            self.assertLess(abs(report['posteriors'][0][1] - D(6) / 7), D('1e-8'))


class IntervalArchiveTests(unittest.TestCase):
    def test_freeze_correction_reopen_and_retry(self):
        import tempfile
        from pathlib import Path
        case = cases()['switch']
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'archive.sqlite'
            store = ArchiveStore.open(path)
            receipt = register(store, case['definition'])
            observations = apply_observations(store, 'stream', case['changes'])
            old_task = create_task(store, 'm', receipt.revision, 'stream',
                                   observations.revision, case['T'],
                                   case['queries'], case['windows'])
            # Correct the observations after freezing; the old task must not change.
            apply_observations(store, 'stream', [
                exact_change('left', '.3', 'a', revision=2)])
            store.close()
            store = ArchiveStore.open(path)
            old_id = analyze_task(store, old_task)
            old_report = read_report(store, old_id)
            self.assertIn('interval', old_report['alarms'][0])

            def fail():
                raise RuntimeError('publication interrupted')
            corrected = apply_observations(store, 'stream', case['changes'])
            new_task = create_task(store, 'm', receipt.revision, 'stream',
                                   corrected.revision, case['T'],
                                   case['queries'], case['windows'])
            with self.assertRaisesRegex(RuntimeError, 'publication interrupted'):
                analyze_task(store, new_task, before_commit=fail)
            self.assertEqual(
                store.connection.execute('SELECT status FROM tasks WHERE task_id=?',
                                         (new_task,)).fetchone()[0], 'READY')
            store.close()
            store = ArchiveStore.open(path)
            new_id = analyze_task(store, new_task)
            self.assertEqual(analyze_task(store, new_task), new_id)
            self.assertEqual(read_report(store, old_id), old_report)
            self.assertEqual(decode_report(encode_report(old_report)), old_report)
            store.close()


def _run(definition, changes, windows):
    with ArchiveStore.open() as store:
        receipt = register(store, definition)
        observations = apply_observations(store, 'stream', changes)
        task = create_task(store, 'm', receipt.revision, 'stream',
                           observations.revision, 1, [D(1)], windows)
        return read_report(store, analyze_task(store, task))


if __name__ == '__main__':
    unittest.main()
