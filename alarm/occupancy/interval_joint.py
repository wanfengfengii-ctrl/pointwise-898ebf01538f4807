"""Conditional occupancy moments jointly integrated with interval identities.

The augmented moment state keeps zero-, first- and mixed-second-order path
integral channels per hidden state (same channel construction as the exact
machinery) for every identity-completion stage of a fixed ordering.  Each
elementary piece is advanced by one block-upper-triangular matrix exponential
whose diagonal blocks are the augmented silence generator and whose single
super-diagonal carries the next identity's mark rate through every channel.
This consumes exactly the same identity completion semantics as the likelihood
and posterior propagation: every interval identity fires once across every
feasible placement and ordering, without width or permutation divisors.
Ordering results merge under one common evidence denominator before the
covariance is formed.
"""
from dataclasses import dataclass
from decimal import Decimal, localcontext, MAX_EMAX, MIN_EMIN
from alarm.evidence.interval import _apply_exact, _concat
from alarm.evidence.matrix import matrix_exponential, row_matrix_multiply
from alarm.occupancy.integrals import build_integral_channels, build_augmented_generator
from alarm.occupancy.numerics import (
    required_precision, validate_joint_moments, OccupancyNumericalError)
from alarm.occupancy.joint import covariance_from_raw_moments


@dataclass(frozen=True)
class IntervalOccupancyResult:
    axes: tuple
    means: tuple
    covariance: tuple
    log_scale: Decimal


def _piece_moment_operator(plan, ordering, piece, axes, channels):
    n = len(plan.model.states)
    block_size = n * len(channels)
    stages = len(ordering) + 1
    size = block_size * stages
    generator = build_augmented_generator(plan, axes, channels,
                                          (piece.start + piece.end) / 2)
    duration = (piece.end - piece.start) / plan.T
    matrix = [[Decimal(0) for _ in range(size)] for _ in range(size)]
    # Every diagonal block carries the full augmented silence generator,
    # including the reward couplings between moment channels.
    for stage in range(stages):
        for row in range(block_size):
            for col in range(block_size):
                matrix[stage * block_size + row][stage * block_size + col] = \
                    generator[row][col]
    # The single super-diagonal adds the next identity's mark rate on every
    # moment channel.  The diagonal generator already runs in normalised time
    # (multiplied by T), so the mark rate is scaled by T to keep the same
    # time clock inside the block matrix.
    for stage, identity in enumerate(ordering):
        if identity not in piece.active:
            continue
        rates = plan.model.rates(plan.interval_marks[identity].kind)
        for channel in range(len(channels)):
            for state in range(n):
                matrix[stage * block_size + channel * n + state][
                    (stage + 1) * block_size + channel * n + state] += \
                    rates[state] * plan.T
    return matrix_exponential([[value * duration for value in row] for row in matrix])


def _rescale_moment(blocks, n):
    # Divide every completion-stage block by the largest zero-order block mass
    # (matching the evidence propagation rescale) so relative ratios stay
    # exact and structurally supported tiny values remain nonzero.
    scale = max(sum(block[:n]) for block in blocks).ln()
    if not scale.is_finite():
        raise OccupancyNumericalError('lost common interval evidence mass')
    if any(not value.is_finite() for block in blocks for value in block):
        raise OccupancyNumericalError('nonfinite interval path moment')
    scaled = tuple(tuple((value.ln() - scale).exp() if value else value
                         for value in block) for block in blocks)
    if not any(any(block[:n]) for block in scaled):
        raise OccupancyNumericalError('lost common interval evidence mass')
    return scaled, scale


def propagate_ordering_moments(plan, ordering, axes):
    n = len(plan.model.states)
    channels = build_integral_channels(axes)
    block_size = n * len(channels)
    stages = len(ordering) + 1
    blocks = [tuple(plan.model.initial) + (Decimal(0),) * (block_size - n)]
    blocks += [tuple(Decimal(0) for _ in range(block_size))
               for _ in range(len(ordering))]
    log_scale = Decimal(0)
    piece_iter = iter(plan.pieces)
    mark_iter = iter(plan.mark_cuts)
    piece = next(piece_iter, None)
    marks = next(mark_iter, None)
    while piece is not None or marks is not None:
        next_piece = piece.end if piece is not None else None
        next_mark = marks.time if marks is not None else None
        if next_mark is not None and (next_piece is None or next_mark <= next_piece):
            blocks = list(_apply_exact(tuple(blocks), plan, marks.events))
            marks = next(mark_iter, None)
        else:
            operator = _piece_moment_operator(plan, ordering, piece, axes, channels)
            current = _concat(blocks)
            advanced = tuple(row_matrix_multiply(current, operator))
            blocks = [advanced[stage * block_size:(stage + 1) * block_size]
                      for stage in range(stages)]
            piece = next(piece_iter, None)
        scaled, increment = _rescale_moment(blocks, n)
        blocks = list(scaled)
        log_scale += increment
    # With max-block rescaling the likelihood is the final stage zero-order
    # block mass on the cumulative scaled grid.
    final_mass = sum(blocks[len(ordering)][:n])
    log_scale += final_mass.ln()
    return channels, tuple(blocks), log_scale


def conditional_interval_occupancy(plan, supported_orderings, axes):
    with localcontext() as ctx:
        ctx.prec = max(ctx.prec, required_precision(plan.T, plan.model.numbers()))
        ctx.Emax = MAX_EMAX
        ctx.Emin = MIN_EMIN
        count = len(axes)
        n = len(plan.model.states)
        per_ordering, log_scales = [], []
        for ordering in supported_orderings:
            channels, blocks, log_scale = propagate_ordering_moments(
                plan, ordering, axes)
            per_ordering.append(blocks)
            log_scales.append(log_scale)
        # Uniform cut rescaling leaves each ordering's final-stage channels
        # scaled by its final-stage zero-order fraction.  Divide that fraction
        # out to obtain within-ordering conditional moments, then mix by the
        # ordering posterior probabilities (one shared evidence denominator).
        offset = max(log_scales)
        weights = [(value - offset).exp() for value in log_scales]
        total_weight = sum(weights)
        weights = [value / total_weight for value in weights]
        final_stage_index = len(supported_orderings[0])
        accumulated = None
        for weight, blocks in zip(weights, per_ordering):
            final_stage = blocks[final_stage_index]
            fraction = sum(final_stage[:n])
            if accumulated is None:
                accumulated = [Decimal(0) for _ in final_stage]
            for index, value in enumerate(final_stage):
                accumulated[index] += weight * value / fraction
        final = accumulated
        means = [Decimal(0)] * count
        raw = [[Decimal(0) for _ in range(count)] for _ in range(count)]
        for block, channel in enumerate(channels):
            value = sum(final[block * n:(block + 1) * n])
            if channel.order == 1:
                means[channel.left] = value
            elif channel.order == 2:
                raw[channel.left][channel.right] = value
                raw[channel.right][channel.left] = value
        covariance = covariance_from_raw_moments(means, raw)
        lengths = tuple((axis.end - axis.start) / plan.T for axis in axes)
        validate_joint_moments(means, covariance, lengths)
        log_likelihood = offset + sum(
            (value - offset).exp() for value in log_scales).ln()
        return IntervalOccupancyResult(
            tuple(axes), tuple(value * plan.T for value in means),
            tuple(tuple(value * plan.T * plan.T for value in row) for row in covariance),
            log_likelihood)
