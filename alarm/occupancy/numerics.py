from decimal import Decimal
from alarm.evidence.matrix import matrix_exponential, row_matrix_multiply


class OccupancyNumericalError(ArithmeticError):
    pass


def required_precision(T, values=()):
    digits = max((len(x.as_tuple().digits) for x in values), default=1)
    return max(90 + 2 * max(0, T.adjusted()) if T else 90, digits + 50)


def rescale_moment_channels(values, n, log_scale):
    mass = sum(values[:n])
    if mass <= 0 or not mass.is_finite():
        raise OccupancyNumericalError('lost common evidence mass')
    if any(not x.is_finite() for x in values):
        raise OccupancyNumericalError('nonfinite path moment')
    return tuple(x / mass for x in values), log_scale + mass.ln()


def propagate_augmented_state(values, generator, duration):
    operator = matrix_exponential([[x * duration for x in row] for row in generator])
    return tuple(row_matrix_multiply(values, operator))


def validate_joint_moments(means, covariance, lengths):
    n = len(means)
    tolerance = Decimal('1e-25')
    if len(covariance) != n or any(len(row) != n for row in covariance):
        raise OccupancyNumericalError('joint result shape mismatch')
    if any(not x.is_finite() for x in means) or any(
            not x.is_finite() for row in covariance for x in row):
        raise OccupancyNumericalError('nonfinite joint result')
    for i in range(n):
        if means[i] < -tolerance or means[i] > lengths[i] + tolerance:
            raise OccupancyNumericalError('mean outside window bounds')
        if covariance[i][i] < -tolerance:
            raise OccupancyNumericalError('negative conditional variance')
        for j in range(n):
            if abs(covariance[i][j] - covariance[j][i]) > tolerance:
                raise OccupancyNumericalError('asymmetric covariance')
    work = [list(row) for row in covariance]
    for i in range(n):
        pivot = max(range(i, n), key=lambda j: work[j][j])
        work[i], work[pivot] = work[pivot], work[i]
        for row in work:
            row[i], row[pivot] = row[pivot], row[i]
        diagonal = work[i][i]
        if diagonal < -tolerance:
            raise OccupancyNumericalError('indefinite covariance')
        if abs(diagonal) <= tolerance:
            if any(abs(work[i][j]) > tolerance for j in range(i + 1, n)):
                raise OccupancyNumericalError('inconsistent null covariance direction')
            continue
        for j in range(i + 1, n):
            for k in range(i + 1, n):
                work[j][k] -= work[j][i] * work[i][k] / diagonal
