import unittest
from decimal import Decimal as D, localcontext
from alarm.archive.storage import ArchiveStore
from alarm.evidence.propagation import ImpossibleEvidence
from examples.interval_cases import cases, expected, assert_expected
from tests.support import analyze


class IntervalExampleTests(unittest.TestCase):
    def test_elementary_switch_material(self):
        with localcontext() as ctx:
            ctx.prec = 90
            result = expected('switch')
            mass = D(-1).exp() * (3 * D(-1).exp() - 1)
            self.assertLess(abs(result['log_likelihood'] - mass.ln()), D('1e-70'))
            self.assertLess(abs(result['means'][0] -
                                D('.1201168277354168578085181429128671840835302487812621763627031554')),
                            D('1e-60'))
            self.assertLess(abs(result['covariance'][0][1] -
                                D('.0084646387880784416516240002939957863927498594675634057347493636')),
                            D('1e-60'))
            self.assertEqual(result['covariance'][0][1], result['covariance'][1][0])
            self.assertEqual(result['posteriors'][0], [D(0), D(1)])
            assert_expected(result, 'switch')

    def test_static_and_rare_material(self):
        with localcontext() as ctx:
            ctx.prec = 90
            case = cases()['static']
            weights = [D('.4') * D('-1.5').exp(),
                       D('.6') * 4 * D('-2.25').exp()]
            result = expected('static')
            self.assertLess(abs(result['log_likelihood'] -
                                (sum(weights) * D('.375')).ln()), D('1e-70'))
            self.assertLess(result['covariance'][0][1], 0)
            rare = expected('rare')
            self.assertTrue(rare['log_likelihood'].is_finite())
            self.assertLess(rare['log_likelihood'], D(-1300))
            self.assertLess(abs(rare['posteriors'][0][1] - D(6) / 7), D('1e-70'))
            case['changes'][0]['interval'][0] = D(99)
            self.assertEqual(cases()['static']['changes'][0]['interval'][0], D(0))

    def test_existing_midpoint_interpretation_is_impossible(self):
        case = cases()['switch']
        changes = [{'alarm_id': r['alarm_id'], 'source_revision': r['source_revision'],
                    'action': 'put', 'time': D('.5'), 'kind': r['kind']}
                   for r in case['changes']]
        with ArchiveStore.open() as store:
            with self.assertRaises(ImpossibleEvidence):
                analyze(store, case['definition'], changes, T=case['T'])
        self.assertGreater(expected('switch')['log_likelihood'].exp(), 0)
