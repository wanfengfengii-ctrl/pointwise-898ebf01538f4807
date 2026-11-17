from alarm.models.types import identifier, number
from alarm.observations.records import ObservationChange, SourceVersion


class ObservationValidationError(ValueError):
    pass


class ObservationRevisionConflict(ValueError):
    pass


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
                time = number(change.time)
                if time < 0:
                    raise ValueError('negative alarm time')
                kind = identifier(change.kind)
            elif change.action == 'withdraw':
                if change.time is not None or change.kind is not None:
                    raise ValueError('withdrawal must not contain event fields')
                time, kind = None, None
            else:
                raise ValueError('unknown observation action')
            value = SourceVersion(identity, revision, change.action, time, kind)
            key = identity, revision
            if key in versions and versions[key].content() != value.content():
                raise ObservationRevisionConflict(key)
            versions[key] = value
    except ObservationRevisionConflict:
        raise
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ObservationValidationError(str(exc)) from exc
    return tuple(versions[key] for key in sorted(versions))
