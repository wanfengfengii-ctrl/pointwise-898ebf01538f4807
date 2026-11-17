from decimal import Decimal, localcontext, getcontext, MAX_EMAX, MIN_EMIN


class MatrixNumericalError(ArithmeticError):
    pass


def identity_matrix(n):
    return [[Decimal(int(i == j)) for j in range(n)] for i in range(n)]


def matrix_multiply(left, right):
    if not left or not right or any(len(row) != len(right) for row in left):
        raise MatrixNumericalError('matrix shape mismatch')
    width = len(right[0])
    if any(len(row) != width for row in right):
        raise MatrixNumericalError('ragged matrix')
    result = [[Decimal(0) for _ in range(width)] for _ in left]
    sparse = [[(j, v) for j, v in enumerate(row) if v] for row in right]
    for i, row in enumerate(left):
        for k, value in enumerate(row):
            if value:
                for j, other in sparse[k]:
                    result[i][j] += value * other
    return result


def row_matrix_multiply(row, matrix):
    if len(row) != len(matrix):
        raise MatrixNumericalError('row shape mismatch')
    return matrix_multiply([row], matrix)[0]


def matrix_exponential(matrix):
    n = len(matrix)
    if not n or any(len(row) != n for row in matrix):
        raise MatrixNumericalError('exponential requires a square matrix')
    if any(not isinstance(v, Decimal) or not v.is_finite() for row in matrix for v in row):
        raise MatrixNumericalError('exponential requires finite Decimal entries')
    with localcontext() as ctx:
        ctx.prec = max(60, getcontext().prec)
        ctx.Emax = MAX_EMAX
        ctx.Emin = MIN_EMIN
        norm = max(sum(abs(v) for v in row) for row in matrix)
        squarings = 0
        while norm > Decimal('0.25'):
            norm /= 2
            squarings += 1
        factor = Decimal(2) ** squarings
        scaled = [[v / factor for v in row] for row in matrix]
        result = identity_matrix(n)
        term = identity_matrix(n)
        tolerance = Decimal(1).scaleb(-ctx.prec + 10)
        for order in range(1, 8 * ctx.prec + 100):
            term = matrix_multiply(term, scaled)
            term = [[v / order for v in row] for row in term]
            result = [[a + b for a, b in zip(row, addition)]
                      for row, addition in zip(result, term)]
            if max(sum(abs(v) for v in row) for row in term) < tolerance:
                break
        else:
            raise MatrixNumericalError('exponential series did not converge')
        for _ in range(squarings):
            result = matrix_multiply(result, result)
        if any(not v.is_finite() for row in result for v in row):
            raise MatrixNumericalError('nonfinite exponential')
        return result
