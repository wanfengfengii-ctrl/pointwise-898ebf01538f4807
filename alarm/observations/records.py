from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ObservationChange:
    alarm_id: str
    source_revision: int
    action: str
    time: object = None
    kind: object = None


@dataclass(frozen=True)
class ObservationRecord:
    alarm_id: str
    source_revision: int
    time: Decimal
    kind: str


@dataclass(frozen=True)
class SourceVersion:
    alarm_id: str
    source_revision: int
    action: str
    time: object = None
    kind: object = None

    def content(self):
        return self.action, self.time, self.kind

    def active_record(self):
        if self.action == 'put':
            return ObservationRecord(self.alarm_id, self.source_revision, self.time, self.kind)
        return None


@dataclass(frozen=True)
class ObservationRevision:
    sequence_id: str
    revision: int
    sources: tuple
    records: tuple
