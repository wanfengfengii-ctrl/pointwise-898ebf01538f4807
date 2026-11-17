from alarm.models.types import identifier, number
from alarm.observations.records import ObservationChange, SourceVersion


class ObservationValidationError(ValueError):
    pass


class ObservationRevisionConflict(ValueError):
    pass


def validate_interval(value):
    if not isinstance(value, (list, tuple)):
        raise ValueError('interval must be a two-item list or tuple')
    if len(value) != 2:
        raise ValueError('interval must contain exactly two endpoints')
    lo, hi = number(value[0]), number(value[1])
    if lo < 0 or not lo < hi:
        raise ValueError('interval must satisfy 0 <= lo < hi')
    # Copy the accepted endpoints so caller mutation cannot reach the archive.
    return lo, hi


def validate_observation_batch(changes):
    versions = {}
    try:
        for change in changes:
            if isinstance(change, dict):
                change = ObservationChange(**change)
            if not isinstance(change, ObservationChange):
                raise ValueError('expected ObservationChange or matching dictionary')
            identity = identifier(change.alarm_id)
            revision = change.source_revision
            if isinstance(revision, bool) or not isinstance(revision, int) or revision < 1:
                raise ValueError('source revision must be a positive integer')
            if change.action == 'put':
                has_time = change.time is not None
                has_interval = change.interval is not None
                if has_time == has_interval:
                    raise ValueError('put requires exactly one of time or interval')
                kind = identifier(change.kind)
                if has_time:
                    time = number(change.time)
                    if time < 0:
                        raise ValueError('negative alarm time')
                    interval = None
                else:
                    time = None
                    interval = validate_interval(change.interval)
            elif change.action == 'withdraw':
                if (change.time is not None or change.kind is not None
                        or change.interval is not None):
                    raise ValueError('withdrawal must not contain event fields')
                time, kind, interval = None, None, None
            else:
                raise ValueError('unknown observation action')
            value = SourceVersion(identity, revision, change.action, time, kind, interval)
            key = identity, revision
            if key in versions and versions[key].content() != value.content():
                raise ObservationRevisionConflict(key)
            versions[key] = value
    except ObservationRevisionConflict:
        raise
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ObservationValidationError(str(exc)) from exc
    return tuple(versions[key] for key in sorted(versions))
