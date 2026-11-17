from dataclasses import dataclass
from alarm.models.types import identifier, number


@dataclass(frozen=True)
class OccupancyRequest:
    state: str
    start: object
    end: object
    label: str = ''


@dataclass(frozen=True)
class OccupancyAxis:
    index: int
    state: str
    start: object
    end: object
    label: str


class OccupancyRequestError(ValueError):
    pass


def validate_occupancy_requests(model, T, requests):
    axes = []
    try:
        for index, request in enumerate(requests):
            if isinstance(request, dict):
                request = OccupancyRequest(**request)
            if not isinstance(request, OccupancyRequest):
                raise ValueError('expected OccupancyRequest or matching dictionary')
            state = identifier(request.state)
            start, end = number(request.start), number(request.end)
            if state not in model.states or not 0 <= start <= end <= T:
                raise ValueError('unknown state or invalid occupancy window')
            if not isinstance(request.label, str):
                raise ValueError('window label must be a string')
            axes.append(OccupancyAxis(index, state, start, end, request.label))
        if len(axes) > 4:
            raise ValueError('at most four occupancy axes')
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise OccupancyRequestError(str(exc)) from exc
    return tuple(axes)
