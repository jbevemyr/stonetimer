"""
StoneTimer timing state machine.

Pure logic, no I/O: no sockets, GPIO, speech or files. The server feeds it
triggers and arm/disarm requests and acts on the events it returns. Not
thread-safe on its own; the caller serializes access.
"""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Callable, Optional

DEVICE_IDS = ('tee', 'hog_close', 'hog_far')


class SystemState(str, Enum):
    IDLE = "idle"
    ARMED = "armed"
    MEASURING = "measuring"
    COMPLETED = "completed"


class EventKind(str, Enum):
    ARMED = "armed"
    DISARMED = "disarmed"
    MEASURING_STARTED = "measuring_started"
    # A sensor timestamp was recorded without producing a split time yet (tee).
    TRIGGER_RECORDED = "trigger_recorded"
    # Tee→hog time is available (value = ms). A history record was created.
    TEE_HOG = "tee_hog"
    # Hog→hog time is available (value = ms). The history record was updated.
    HOG_HOG = "hog_hog"


@dataclass(frozen=True)
class Event:
    kind: EventKind
    value: Optional[float] = None


@dataclass
class TimingRecord:
    id: int
    timestamp: datetime
    tee_to_hog_close_ms: float
    hog_to_hog_ms: Optional[float] = None  # None if the stone did not reach hog_far
    total_ms: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'tee_to_hog_close_ms': self.tee_to_hog_close_ms,
            'hog_to_hog_ms': self.hog_to_hog_ms,
            'total_ms': self.total_ms,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "TimingRecord":
        def opt_float(value):
            return None if value is None else float(value)

        return cls(
            id=int(data['id']),
            timestamp=datetime.fromisoformat(data['timestamp']),
            tee_to_hog_close_ms=float(data['tee_to_hog_close_ms']),
            hog_to_hog_ms=opt_float(data.get('hog_to_hog_ms')),
            total_ms=opt_float(data.get('total_ms')),
        )


class TimingSession:
    """Timestamps for the run currently being measured."""

    def __init__(self):
        self.reset()

    def reset(self):
        self.tee_time_ns: Optional[int] = None
        self.hog_close_time_ns: Optional[int] = None
        self.hog_far_time_ns: Optional[int] = None
        self.started_at: Optional[datetime] = None
        # History record created for this run (set once hog_close is seen).
        self.record_id: Optional[int] = None

    @staticmethod
    def _diff_ms(start_ns: Optional[int], end_ns: Optional[int]) -> Optional[float]:
        if start_ns is None or end_ns is None:
            return None
        return (end_ns - start_ns) / 1_000_000

    @property
    def tee_to_hog_close_ms(self) -> Optional[float]:
        return self._diff_ms(self.tee_time_ns, self.hog_close_time_ns)

    @property
    def hog_to_hog_ms(self) -> Optional[float]:
        return self._diff_ms(self.hog_close_time_ns, self.hog_far_time_ns)

    @property
    def total_ms(self) -> Optional[float]:
        return self._diff_ms(self.tee_time_ns, self.hog_far_time_ns)

    @property
    def has_hog_close(self) -> bool:
        """True if the stone passed the near hog line."""
        return self.tee_time_ns is not None and self.hog_close_time_ns is not None

    @property
    def has_hog_far(self) -> bool:
        """True if the stone passed the far hog line."""
        return self.hog_far_time_ns is not None

    def to_dict(self) -> dict:
        return {
            'tee_time_ns': self.tee_time_ns,
            'hog_close_time_ns': self.hog_close_time_ns,
            'hog_far_time_ns': self.hog_far_time_ns,
            'tee_to_hog_close_ms': self.tee_to_hog_close_ms,
            'hog_to_hog_ms': self.hog_to_hog_ms,
            'total_ms': self.total_ms,
            'has_hog_close': self.has_hog_close,
            'has_hog_far': self.has_hog_far,
            'started_at': self.started_at.isoformat() if self.started_at else None
        }


class TimingCore:
    """State machine for one sheet.

        IDLE → ARMED (arm)
        ARMED → MEASURING (first trigger)
        MEASURING → COMPLETED (hog_close after tee)
        MEASURING/COMPLETED → ARMED (arm, e.g. after an accidental trigger)
        any → IDLE (disarm)

    hog_far needs hog_close first, and hog_close completes the run, so hog_far
    is only ever accepted in COMPLETED, where it updates that run's record.
    """

    def __init__(
        self,
        max_history: int = 100,
        history: Optional[list[TimingRecord]] = None,
        now: Callable[[], datetime] = datetime.now,
    ):
        self.state = SystemState.IDLE
        self.session = TimingSession()
        self.max_history = max_history
        self.history: list[TimingRecord] = list(history or [])[:max_history]
        self._next_id = max((r.id for r in self.history), default=0) + 1
        self._now = now
        # Incremented each time a measurement starts; lets timers tell runs apart.
        self.measurement_token = 0
        # Sensors send each trigger several times; remember what we've seen.
        self._recent_triggers: deque = deque(maxlen=64)

    # --- commands -----------------------------------------------------

    def arm(self) -> list[Event]:
        """Arm the system. Allowed from IDLE, COMPLETED or MEASURING."""
        if self.state == SystemState.ARMED:
            return []
        self.session.reset()
        self.state = SystemState.ARMED
        return [Event(EventKind.ARMED)]

    def disarm(self) -> list[Event]:
        self.session.reset()
        self.state = SystemState.IDLE
        return [Event(EventKind.DISARMED)]

    def handle_trigger(self, device_id: str, timestamp_ns: int) -> list[Event]:
        """Process a sensor trigger. Returns the resulting events (possibly none)."""
        if device_id not in DEVICE_IDS:
            return []

        key = (device_id, timestamp_ns)
        if key in self._recent_triggers:
            return []
        self._recent_triggers.append(key)

        session = self.session

        # hog_far normally arrives after the run completed: update that run.
        if self.state == SystemState.COMPLETED:
            if device_id == 'hog_far':
                return self._record_hog_far(timestamp_ns)
            return []

        if self.state not in (SystemState.ARMED, SystemState.MEASURING):
            return []

        events: list[Event] = []

        # First trigger starts the measurement
        if self.state == SystemState.ARMED:
            self.state = SystemState.MEASURING
            session.started_at = self._now()
            self.measurement_token += 1
            events.append(Event(EventKind.MEASURING_STARTED))

        # Record the first timestamp per sensor, in the order the stone travels.
        if device_id == 'tee':
            if session.tee_time_ns is None:
                session.tee_time_ns = timestamp_ns
                events.append(Event(EventKind.TRIGGER_RECORDED))

        elif device_id == 'hog_close':
            # Ignore hog_close without (or before) tee
            if (session.hog_close_time_ns is None
                    and session.tee_time_ns is not None
                    and timestamp_ns > session.tee_time_ns):
                session.hog_close_time_ns = timestamp_ns
                events.append(self._complete_measurement())

        elif device_id == 'hog_far':
            events.extend(self._record_hog_far(timestamp_ns))

        return events

    def _complete_measurement(self) -> Event:
        """hog_close seen: the run is complete as far as tee→hog goes."""
        session = self.session
        self.state = SystemState.COMPLETED

        record = TimingRecord(
            id=self._next_id,
            timestamp=session.started_at or self._now(),
            tee_to_hog_close_ms=session.tee_to_hog_close_ms,
        )
        self._next_id += 1
        session.record_id = record.id
        self.history.insert(0, record)
        del self.history[self.max_history:]

        return Event(EventKind.TEE_HOG, record.tee_to_hog_close_ms)

    def _record_hog_far(self, timestamp_ns: int) -> list[Event]:
        session = self.session
        if session.hog_far_time_ns is not None:
            return []
        # Ignore hog_far without (or before) hog_close
        if session.hog_close_time_ns is None or timestamp_ns <= session.hog_close_time_ns:
            return []

        session.hog_far_time_ns = timestamp_ns
        # The record may have been deleted or the history cleared in the meantime.
        for record in self.history:
            if record.id == session.record_id:
                record.hog_to_hog_ms = session.hog_to_hog_ms
                record.total_ms = session.total_ms
                break
        return [Event(EventKind.HOG_HOG, session.hog_to_hog_ms)]

    # --- history ------------------------------------------------------

    def delete_record(self, record_id: int) -> bool:
        for i, record in enumerate(self.history):
            if record.id == record_id:
                self.history.pop(i)
                return True
        return False

    def clear_history(self) -> None:
        self.history.clear()
        self._next_id = 1

    def history_dicts(self, limit: Optional[int] = None) -> list[dict]:
        records = self.history if limit is None else self.history[:max(0, limit)]
        return [r.to_dict() for r in records]

    def state_dict(self) -> dict:
        return {
            'state': self.state.value,
            'session': self.session.to_dict(),
        }
