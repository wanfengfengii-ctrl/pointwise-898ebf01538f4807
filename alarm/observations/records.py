from dataclasses import dataclass


@dataclass(frozen=True)
class ObservationChange:
    alarm_id: str
    source_revision: int
    action: str
    time: object = None
    kind: object = None
    interval: object = None


@dataclass(frozen=True)
class ObservationRecord:
    alarm_id: str
    source_revision: int
    time: object
    kind: str
    interval: object = None

    @property
    def location(self):
        return self.time if self.interval is None else self.interval[0]

    @property
    def is_interval(self):
        return self.interval is not None


@dataclass(frozen=True)
class SourceVersion:
    alarm_id: str
    source_revision: int
    action: str
    time: object = None
    kind: object = None
    interval: object = None

    def content(self):
        return self.action, self.time, self.kind, self.interval

    def active_record(self):
        if self.action == 'put':
            return ObservationRecord(self.alarm_id, self.source_revision,
                                     self.time, self.kind, self.interval)
        return None


@dataclass(frozen=True)
class ObservationRevision:
    sequence_id: str
    revision: int
    sources: tuple
    records: tuple
