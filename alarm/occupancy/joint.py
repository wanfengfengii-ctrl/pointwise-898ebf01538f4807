from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from alarm.evidence.timeline import EvidenceInterval, split_evidence_intervals
from alarm.occupancy.integrals import (
    MomentState, build_integral_channels, advance_moments, apply_moment_event)
from alarm.occupancy.numerics import required_precision, validate_joint_moments, OccupancyNumericalError


@dataclass(frozen=True)
class OccupancyResult:
    axes: tuple
    means: tuple
    covariance: tuple


def covariance_from_raw_moments(means, raw):
    return tuple(tuple(raw[i][j] - means[i] * means[j] for j in range(len(means)))
                 for i in range(len(means)))


def conditional_occupancy(evidence, axes):
    plan = evidence.plan
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, required_precision(plan.T, plan.model.numbers()))
        ctx.Emax = MAX_EMAX
        ctx.Emin = MIN_EMIN
        n, count = len(plan.model.states), len(axes)
        channels = build_integral_channels(axes)
        values = tuple(plan.model.initial) + (Decimal(0),) * (n * (len(channels) - 1))
        state = MomentState(values, Decimal(0))
        boundaries = tuple(t for axis in axes for t in (axis.start, axis.end))
        for step in split_evidence_intervals(plan, boundaries):
            if isinstance(step, EvidenceInterval):
                state = advance_moments(state, plan, axes, channels, step)
            else:
                state = apply_moment_event(state, plan, step)
        if abs(state.log_scale - evidence.log_likelihood) > Decimal('1e-20'):
            raise OccupancyNumericalError('evidence and path moments disagree')
        means = [Decimal(0)] * count
        raw = [[Decimal(0) for _ in range(count)] for _ in range(count)]
        for block, channel in enumerate(channels):
            value = sum(state.values[block * n:(block + 1) * n])
            if channel.order == 1:
                means[channel.left] = value
            elif channel.order == 2:
                raw[channel.left][channel.right] = value
                raw[channel.right][channel.left] = value
        covariance = covariance_from_raw_moments(means, raw)
        lengths = tuple((axis.end - axis.start) / plan.T if plan.T else Decimal(0) for axis in axes)
        validate_joint_moments(means, covariance, lengths)
        return OccupancyResult(tuple(axes), tuple(x * plan.T for x in means),
                               tuple(tuple(x * plan.T * plan.T for x in row) for row in covariance))
