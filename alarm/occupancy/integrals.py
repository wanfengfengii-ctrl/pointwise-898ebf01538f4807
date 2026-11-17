from dataclasses import dataclass
from decimal import Decimal
from alarm.evidence.operators import silence_generator, mark_operator
from alarm.occupancy.numerics import propagate_augmented_state, rescale_moment_channels


@dataclass(frozen=True)
class IntegralChannel:
    order: int
    left: int = -1
    right: int = -1


@dataclass(frozen=True)
class MomentState:
    values: tuple
    log_scale: Decimal


def build_integral_channels(axes):
    count = len(axes)
    return (IntegralChannel(0),) + tuple(IntegralChannel(1, i) for i in range(count)) + tuple(
        IntegralChannel(2, i, j) for i in range(count) for j in range(i, count))


def build_augmented_generator(plan, axes, channels, midpoint):
    n = len(plan.model.states)
    size = n * len(channels)
    matrix = [[Decimal(0) for _ in range(size)] for _ in range(size)]
    base = silence_generator(plan.model)
    for block in range(len(channels)):
        for i in range(n):
            for j in range(n):
                matrix[block * n + i][block * n + j] = base[i][j] * plan.T
    rewards = []
    for axis in axes:
        rewards.append(tuple(Decimal(int(axis.start <= midpoint < axis.end and state == axis.state))
                             for state in plan.model.states))
    first = {channel.left: block for block, channel in enumerate(channels) if channel.order == 1}
    for target, channel in enumerate(channels):
        if channel.order == 1:
            for state in range(n):
                matrix[state][target * n + state] += rewards[channel.left][state]
        elif channel.order == 2:
            i, j = channel.left, channel.right
            for state in range(n):
                matrix[first[i] * n + state][target * n + state] += rewards[j][state]
                matrix[first[j] * n + state][target * n + state] += rewards[i][state]
    return matrix


def advance_moments(state, plan, axes, channels, interval):
    if not plan.T or interval.end == interval.start:
        return state
    midpoint = (interval.start + interval.end) / 2
    generator = build_augmented_generator(plan, axes, channels, midpoint)
    duration = (interval.end - interval.start) / plan.T
    values = propagate_augmented_state(state.values, generator, duration)
    values, log_scale = rescale_moment_channels(values, len(plan.model.states), state.log_scale)
    return MomentState(values, log_scale)


def apply_moment_event(state, plan, event):
    n = len(plan.model.states)
    operator = mark_operator(plan.model, event.kind)
    values = tuple(value * operator[i % n][i % n] for i, value in enumerate(state.values))
    values, log_scale = rescale_moment_channels(values, n, state.log_scale)
    return MomentState(values, log_scale)
