import unittest
from copy import deepcopy
from decimal import Decimal
from alarm.archive.storage import ArchiveStore
from alarm.models.repository import register_model, get_model_revision, ModelRequestConflict
from alarm.models.validation import ModelValidationError
from alarm.observations.batches import apply_observations
from alarm.observations.repository import read_observation_revision, read_source_history
from alarm.observations.validation import ObservationRevisionConflict, ObservationValidationError
from tests.support import model, put, withdraw


class ModelTests(unittest.TestCase):
    def test_invalid_generator(self):
        with ArchiveStore.open() as store:
            value = model()
            value['Q'] = [[1, -1], [0, 0]]
            with self.assertRaises(ModelValidationError):
                register_model(store, 'm', 'r', **value)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_revisions').fetchone()[0], 0)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_requests').fetchone()[0], 0)

    def test_registration_identity_and_order(self):
        with ArchiveStore.open() as store:
            value = model(True)
            value['states'] = ['z', 'a']
            receipt = register_model(store, 'm', 'r', **value)
            stored = get_model_revision(store, 'm', receipt.revision)
            self.assertEqual(stored.definition.states, ('z', 'a'))
            self.assertEqual(stored.definition.Q[0][1], Decimal('0.7'))
            self.assertEqual(stored.definition.initial, (Decimal('0.5'), Decimal('0.5')))
            self.assertEqual(stored.definition.rates('a'), (0, 2))
            self.assertEqual(register_model(store, 'm', 'r', **deepcopy(value)), receipt)
            changed = deepcopy(value)
            changed['intensities']['a'] = [1, 2]
            with self.assertRaises(ModelRequestConflict):
                register_model(store, 'm', 'r', **changed)
            successor = register_model(store, 'm', 'next', **changed)
            self.assertEqual(successor.revision, 2)
            self.assertEqual(get_model_revision(store, 'm', 1), stored)
            value['states'][0] = 'mutated'
            self.assertEqual(get_model_revision(store, 'm', 1), stored)

    def test_nonfinite_and_shapes(self):
        cases = []
        for bad in [float('nan'), float('inf'), Decimal('-Infinity'), True]:
            value = model()
            value['initial'] = [bad, 0]
            cases.append(value)
        value = model()
        value['Q'] = [[0], [0]]
        cases.append(value)
        value = model()
        value['initial'] = [Decimal('0.4'), Decimal('0.5')]
        cases.append(value)
        value = model()
        value['intensities']['b'] = [-1, 0]
        cases.append(value)
        with ArchiveStore.open() as store:
            for index, value in enumerate(cases):
                with self.subTest(index=index), self.assertRaises(ModelValidationError):
                    register_model(store, 'm', str(index), **value)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM model_revisions').fetchone()[0], 0)


class ObservationTests(unittest.TestCase):
    def test_conflicting_revision(self):
        with ArchiveStore.open() as store:
            old = apply_observations(store, 's', [put('x', 1, 0), put('y', 1, 1)])
            history = read_source_history(store, 's')
            with self.assertRaises(ObservationRevisionConflict):
                apply_observations(store, 's', [put('x', 2, 2), put('y', 1, 3)])
            self.assertEqual(read_observation_revision(store, 's'), old)
            self.assertEqual(read_source_history(store, 's'), history)
            self.assertEqual(apply_observations(store, 's', [put('x', 2, 2)]).revision, 2)

    def test_stale_tombstone_and_history(self):
        with ArchiveStore.open() as store:
            first = apply_observations(store, 's', [put('x', 1, 0)])
            deleted = apply_observations(store, 's', [withdraw('x', 3)])
            stale = apply_observations(store, 's', [put('x', 2, 1)])
            self.assertEqual(stale, deleted)
            self.assertEqual(stale.records, ())
            self.assertEqual(stale.sources[0].source_revision, 3)
            self.assertEqual(read_observation_revision(store, 's', 1), first)
            with self.assertRaises(ObservationRevisionConflict):
                apply_observations(store, 's', [put('x', 1, 8)])
            restored = apply_observations(store, 's', [put('x', 4, 2)])
            self.assertEqual(restored.records[0].source_revision, 4)

    def test_batch_order_and_coincident_identity(self):
        batch = [put('x', 1, 0), withdraw('x', 3), put('x', 2, 1),
                 put('y', 1, 1), put('z', 1, 1), put('z', 1, 1)]
        with ArchiveStore.open() as store:
            left = apply_observations(store, 'left', batch)
            right = apply_observations(store, 'right', list(reversed(batch)))
            self.assertEqual(left.sources, right.sources)
            self.assertEqual(left.records, right.records)
            self.assertEqual([r.alarm_id for r in left.records], ['y', 'z'])
            self.assertEqual(apply_observations(store, 'left', batch), left)
            self.assertEqual(apply_observations(store, 'empty', []).records, ())

    def test_invalid_records_atomic(self):
        invalid = [put('x', True, 0), put('x', 0, 0), put('x', 1, -1),
                   put('x', 1, float('nan')), put('x', 1, 0, ''),
                   {'alarm_id': 'x', 'source_revision': 1, 'action': 'unknown'},
                   {'alarm_id': 'x', 'source_revision': 1, 'action': 'withdraw', 'time': 0}]
        with ArchiveStore.open() as store:
            for bad in invalid:
                with self.subTest(bad=bad), self.assertRaises(ObservationValidationError):
                    apply_observations(store, 's', [put('valid', 1, 0), bad])
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM observation_revisions').fetchone()[0], 0)
            self.assertEqual(store.connection.execute('SELECT COUNT(*) FROM source_history').fetchone()[0], 0)
            with self.assertRaises(ObservationRevisionConflict):
                apply_observations(store, 's', [put('x', 1, 0), put('x', 1, 1)])
