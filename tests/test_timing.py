"""Tests for the timing state machine (no I/O involved)."""

from timing import EventKind, SystemState, TimingCore, TimingRecord

S = 1_000_000_000  # one second in ns
T0 = 1_700_000_000 * S


def kinds(events):
    return [e.kind for e in events]


def armed_core(**kwargs) -> TimingCore:
    core = TimingCore(**kwargs)
    core.arm()
    return core


def run_stone(core, tee_hog_s=3.0, hog_hog_s=None, start=T0):
    core.arm()
    core.handle_trigger('tee', start)
    core.handle_trigger('hog_close', start + int(tee_hog_s * S))
    if hog_hog_s is not None:
        core.handle_trigger('hog_far', start + int((tee_hog_s + hog_hog_s) * S))


def test_starts_idle_and_ignores_triggers():
    core = TimingCore()
    assert core.state == SystemState.IDLE
    assert core.handle_trigger('tee', T0) == []
    assert core.state == SystemState.IDLE


def test_arm_and_disarm():
    core = TimingCore()
    assert kinds(core.arm()) == [EventKind.ARMED]
    assert core.state == SystemState.ARMED
    assert core.arm() == []  # already armed
    assert kinds(core.disarm()) == [EventKind.DISARMED]
    assert core.state == SystemState.IDLE


def test_full_run():
    core = armed_core()

    events = core.handle_trigger('tee', T0)
    assert kinds(events) == [EventKind.MEASURING_STARTED, EventKind.TRIGGER_RECORDED]
    assert core.state == SystemState.MEASURING

    events = core.handle_trigger('hog_close', T0 + 3 * S)
    assert kinds(events) == [EventKind.TEE_HOG]
    assert events[0].value == 3000.0
    assert core.state == SystemState.COMPLETED
    assert len(core.history) == 1
    assert core.history[0].hog_to_hog_ms is None

    events = core.handle_trigger('hog_far', T0 + 13 * S)
    assert kinds(events) == [EventKind.HOG_HOG]
    assert events[0].value == 10000.0
    assert core.state == SystemState.COMPLETED
    record = core.history[0]
    assert record.tee_to_hog_close_ms == 3000.0
    assert record.hog_to_hog_ms == 10000.0
    assert record.total_ms == 13000.0


def test_duplicate_triggers_are_dropped():
    core = armed_core()
    assert core.handle_trigger('tee', T0)
    assert core.handle_trigger('tee', T0) == []
    assert core.handle_trigger('hog_close', T0 + 3 * S)
    assert core.handle_trigger('hog_close', T0 + 3 * S) == []
    assert len(core.history) == 1


def test_resent_trigger_does_not_start_a_new_run_after_rearm():
    core = armed_core()
    core.handle_trigger('tee', T0)
    core.arm()  # rearm, e.g. accidental trigger
    assert core.state == SystemState.ARMED
    # A late copy of the same trigger must not start measuring again
    assert core.handle_trigger('tee', T0) == []
    assert core.state == SystemState.ARMED


def test_second_trigger_from_same_sensor_is_ignored():
    core = armed_core()
    core.handle_trigger('tee', T0)
    # e.g. the thrower's foot crossing the beam after the stone
    assert core.handle_trigger('tee', T0 + S // 2) == []
    core.handle_trigger('hog_close', T0 + 3 * S)
    assert core.history[0].tee_to_hog_close_ms == 3000.0


def test_hog_close_without_tee_does_not_complete():
    core = armed_core()
    events = core.handle_trigger('hog_close', T0)
    assert kinds(events) == [EventKind.MEASURING_STARTED]
    assert core.state == SystemState.MEASURING
    assert core.history == []
    # tee can still arrive afterwards and the run proceeds normally
    core.handle_trigger('tee', T0 + S)
    core.handle_trigger('hog_close', T0 + 4 * S)
    assert core.state == SystemState.COMPLETED
    assert core.history[0].tee_to_hog_close_ms == 3000.0


def test_hog_close_timestamp_before_tee_is_ignored():
    core = armed_core()
    core.handle_trigger('tee', T0)
    assert core.handle_trigger('hog_close', T0 - S) == []
    assert core.state == SystemState.MEASURING


def test_hog_far_before_hog_close_is_ignored():
    core = armed_core()
    core.handle_trigger('tee', T0)
    assert core.handle_trigger('hog_far', T0 + S) == []
    assert core.session.hog_far_time_ns is None


def test_hog_far_timestamp_before_hog_close_is_ignored():
    core = armed_core()
    core.handle_trigger('tee', T0)
    core.handle_trigger('hog_close', T0 + 3 * S)
    assert core.handle_trigger('hog_far', T0 + 2 * S) == []
    assert core.history[0].hog_to_hog_ms is None


def test_only_first_hog_far_counts():
    core = TimingCore()
    run_stone(core, 3.0, 10.0)
    assert core.handle_trigger('hog_far', T0 + 20 * S) == []
    assert core.history[0].hog_to_hog_ms == 10000.0


def test_late_hog_far_from_previous_stone_after_rearm():
    core = TimingCore()
    run_stone(core, 3.0)
    core.arm()
    # Previous stone reaches the far hog after the rearm: starts "measuring"
    # but must not touch the previous record or produce a time.
    events = core.handle_trigger('hog_far', T0 + 13 * S)
    assert kinds(events) == [EventKind.MEASURING_STARTED]
    assert core.history[0].hog_to_hog_ms is None
    # The next stone is still measured
    core.handle_trigger('tee', T0 + 60 * S)
    core.handle_trigger('hog_close', T0 + 63 * S)
    assert len(core.history) == 2


def test_rearm_while_measuring_resets_session():
    core = armed_core()
    core.handle_trigger('tee', T0)
    assert kinds(core.arm()) == [EventKind.ARMED]
    assert core.session.tee_time_ns is None
    assert core.state == SystemState.ARMED


def test_hog_far_does_not_update_wrong_record_after_delete():
    core = TimingCore()
    run_stone(core, 3.0, start=T0)
    run_stone(core, 3.2, start=T0 + 100 * S)
    current_id = core.history[0].id
    assert core.delete_record(current_id)
    events = core.handle_trigger('hog_far', T0 + 115 * S)
    # The time is still reported for the session, but the remaining (older) record is untouched
    assert kinds(events) == [EventKind.HOG_HOG]
    assert len(core.history) == 1
    assert core.history[0].hog_to_hog_ms is None


def test_measurement_token_increments_per_run():
    core = TimingCore()
    run_stone(core, start=T0)
    run_stone(core, start=T0 + 100 * S)
    assert core.measurement_token == 2


def test_history_is_newest_first_and_capped():
    core = TimingCore(max_history=3)
    for i in range(5):
        run_stone(core, 3.0 + i / 10, start=T0 + i * 100 * S)
    assert [r.id for r in core.history] == [5, 4, 3]


def test_history_restored_continues_ids():
    core = TimingCore()
    run_stone(core, 3.0, 10.0)
    run_stone(core, 3.1, start=T0 + 100 * S)
    restored = [TimingRecord.from_dict(d) for d in core.history_dicts()]
    assert restored == core.history

    core2 = TimingCore(history=restored)
    run_stone(core2, 3.2, start=T0 + 200 * S)
    assert [r.id for r in core2.history] == [3, 2, 1]


def test_clear_history_resets_ids():
    core = TimingCore()
    run_stone(core)
    core.clear_history()
    run_stone(core, start=T0 + 100 * S)
    assert [r.id for r in core.history] == [1]


def test_unknown_device_is_ignored():
    core = armed_core()
    assert core.handle_trigger('bogus', T0) == []
    assert core.state == SystemState.ARMED
