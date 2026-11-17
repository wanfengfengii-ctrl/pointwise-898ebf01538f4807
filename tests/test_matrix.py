import unittest
from decimal import Decimal, localcontext
from alarm.evidence.matrix import matrix_exponential, matrix_multiply, identity_matrix
from tests.support import D, close_decimal


class MatrixTests(unittest.TestCase):
    def test_zero_and_diagonal(self):
        self.assertEqual(matrix_exponential([[D(0), D(0)], [D(0), D(0)]]), identity_matrix(2))
        result = matrix_exponential([[D(-3), D(0)], [D(0), D(2)]])
        with localcontext() as ctx:
            ctx.prec = 70
            close_decimal(self, result[0][0], D(-3).exp())
            close_decimal(self, result[1][1], D(2).exp())
            self.assertEqual(result[0][1], 0)
            self.assertEqual(result[1][0], 0)

    def test_two_state_and_semigroup(self):
        with localcontext() as ctx:
            ctx.prec = 80
            a, b, T = D('0.7'), D('0.4'), D('2.3')
            matrix = [[-a * T, a * T], [b * T, -b * T]]
            actual = matrix_exponential(matrix)
            e = (-(a + b) * T).exp()
            expected = [[(b + a * e) / (a + b), a * (1 - e) / (a + b)],
                        [b * (1 - e) / (a + b), (a + b * e) / (a + b)]]
            for i in range(2):
                for j in range(2):
                    close_decimal(self, actual[i][j], expected[i][j], D('1e-50'))
            half = matrix_exponential([[x / 2 for x in row] for row in matrix])
            squared = matrix_multiply(half, half)
            for i in range(2):
                for j in range(2):
                    close_decimal(self, actual[i][j], squared[i][j], D('1e-50'))

    def test_nonnormal_jordan(self):
        with localcontext() as ctx:
            ctx.prec = 80
            actual = matrix_exponential([[D(1), D(3), D(0)],
                                         [D(0), D(1), D(2)],
                                         [D(0), D(0), D(1)]])
            e = D(1).exp()
            expected = [[e, 3 * e, 3 * e], [D(0), e, 2 * e], [D(0), D(0), e]]
            for i in range(3):
                for j in range(3):
                    close_decimal(self, actual[i][j], expected[i][j], D('1e-50'))
