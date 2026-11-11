"""Tests for the server wrapper: API, persistence, UDP handling, clock check."""

import json
import socket
import time

import pytest
from fastapi.testclient import TestClient

import main
from main import Settings, StoneTimerServer, create_app, spoken_time

S = 1_000_000_000
T0 = 1_700_000_000 * S
ADDR = ('192.168.50.11', 40000)


def make_config(**server_overrides):
    server = {
        'host': '127.0.0.1',
        'http_port': 8080,
        'udp_port': 0,  # any free port
        'enable_speech': False,
    }
    server.update(server_overrides)
    return {'device_id': 'hog_close', 'gpio': {'sensor_pin': 17, 'debounce_ms': 50}, 'server': server}


@pytest.fixture
def server(tmp_path):
    return StoneTimerServer(config=make_config(), data_dir=tmp_path)


@pytest.fixture
def client(server):
    with TestClient(create_app(server)) as c:
        yield c


def run_stone(server, tee_hog_s=3.0, hog_hog_s=None, start=T0):
    server.arm()
    server.handle_trigger('tee', start)
    server.handle_trigger('hog_close', start + int(tee_hog_s * S))
    if hog_hog_s is not None:
        server.handle_trigger('hog_far', start + int((tee_hog_s + hog_hog_s) * S))


def datagram(**payload) -> bytes:
    return json.dumps(payload).encode()


# --- speech formatting -----------------------------------------------------

@pytest.mark.parametrize("ms, expected", [
    (3180, "3 point 18"),
    (3100, "3 point 10"),
    (3060, "3 point oh 6"),
    (3000, "3 point 00"),
    (12345, "12 point 35"),
])
def test_spoken_time(ms, expected):
    assert spoken_time(ms) == expected


# --- API ---------------------------------------------------------------------

def test_arm_disarm_and_status(client):
    assert client.get('/api/status').json()['state'] == 'idle'
    assert client.post('/api/arm').json() == {'success': True, 'state': 'armed'}
    assert client.post('/api/arm').json() == {'success': False, 'state': 'armed'}
    assert client.post('/api/disarm').json() == {'success': True, 'state': 'idle'}


def test_run_shows_up_in_api(client, server):
    run_stone(server, 3.05, 10.5)
    status = client.get('/api/status').json()
    assert status['state'] == 'completed'
    assert status['session']['tee_to_hog_close_ms'] == pytest.approx(3050)
    assert client.get('/api/current').json()['hog_to_hog_ms'] == pytest.approx(10500)

    times = client.get('/api/times').json()
    assert len(times) == 1
    assert times[0]['tee_to_hog_close_ms'] == pytest.approx(3050)
    assert times[0]['total_ms'] == pytest.approx(13550)


def test_delete_and_clear_history(client, server):
    run_stone(server, start=T0)
    run_stone(server, start=T0 + 100 * S)
    first_id = client.get('/api/times').json()[-1]['id']
    assert client.delete(f'/api/times/{first_id}').json() == {'success': True}
    assert client.delete(f'/api/times/{first_id}').json() == {'success': False}
    assert len(client.get('/api/times').json()) == 1
    assert client.post('/api/clear').json() == {'success': True}
    assert client.get('/api/times').json() == []


def test_sensors_endpoint_shape(client):
    data = client.get('/api/sensors').json()
    assert [s['device_id'] for s in data['sensors']] == ['tee', 'hog_close', 'hog_far']
    assert [s['status'] for s in data['sensors']] == ['offline', 'local', 'offline']


# --- settings ----------------------------------------------------------------

def test_partial_settings_update_keeps_other_values(client, server):
    full = {
        'speech_enabled': True, 'speak_ready': False, 'speak_tee_hog': True,
        'speak_hog_hog': True, 'auto_rearm_enabled': True, 'auto_rearm_after_s': 90,
    }
    assert client.post('/api/settings', json=full).status_code == 200
    assert client.get('/api/settings').json() == full

    # Leaving keys out must not reset them
    assert client.post('/api/settings', json={'speak_hog_hog': False}).status_code == 200
    assert client.get('/api/settings').json() == {**full, 'speak_hog_hog': False}


def test_settings_clamp_and_validate(client):
    client.post('/api/settings', json={'auto_rearm_after_s': 999999})
    assert client.get('/api/settings').json()['auto_rearm_after_s'] == 30 * 60
    client.post('/api/settings', json={'auto_rearm_after_s': -5})
    assert client.get('/api/settings').json()['auto_rearm_after_s'] == 0
    # iOS sends seconds as a float
    client.post('/api/settings', json={'auto_rearm_after_s': 90.0})
    assert client.get('/api/settings').json()['auto_rearm_after_s'] == 90

    before = client.get('/api/settings').json()
    assert client.post('/api/settings', json={'speech_enabled': 'banana'}).status_code == 422
    assert client.get('/api/settings').json() == before


def test_settings_persist_across_restart(tmp_path):
    first = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    first.update_settings(main.SettingsUpdate(speech_enabled=True, auto_rearm_after_s=300))
    second = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    assert second.settings.speech_enabled is True
    assert second.settings.auto_rearm_after_s == 300


def test_settings_defaults_come_from_config(tmp_path):
    config = make_config(enable_speech=True, speech={'speak_hog_hog': True},
                         auto_rearm={'enabled': True, 'after_s': 45})
    server = StoneTimerServer(config=config, data_dir=tmp_path)
    assert server.settings == Settings(speech_enabled=True, speak_hog_hog=True,
                                       auto_rearm_enabled=True, auto_rearm_after_s=45)


def test_corrupt_runtime_settings_are_ignored(tmp_path):
    (tmp_path / 'runtime_settings.json').write_text('{"speech_enabled": "banana"}')
    server = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    assert server.settings == Settings()


# --- history persistence -------------------------------------------------------

def test_history_persists_across_restart(tmp_path):
    first = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    run_stone(first, 3.0, 10.0, start=T0)
    run_stone(first, 3.2, start=T0 + 100 * S)

    second = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    assert second.get_history() == first.get_history()
    assert second.get_history()[1]['hog_to_hog_ms'] == pytest.approx(10000)

    run_stone(second, 3.4, start=T0 + 200 * S)
    assert [r['id'] for r in second.get_history()] == [3, 2, 1]


def test_clear_history_is_persisted(tmp_path):
    first = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    run_stone(first)
    first.clear_history()
    assert StoneTimerServer(config=make_config(), data_dir=tmp_path).get_history() == []


def test_corrupt_history_file_is_ignored(tmp_path):
    (tmp_path / 'history.json').write_text('{not json')
    server = StoneTimerServer(config=make_config(), data_dir=tmp_path)
    assert server.get_history() == []
    run_stone(server)
    assert len(server.get_history()) == 1


# --- UDP handling ----------------------------------------------------------------

@pytest.mark.parametrize("data", [
    b'\xff\xfe not utf-8',
    b'not json',
    b'[1, 2, 3]',
    b'"just a string"',
    b'null',
    datagram(type='trigger'),
    datagram(type='trigger', device_id='tee', timestamp_ns='soon'),
    datagram(type='trigger', device_id=['tee'], timestamp_ns=T0),
    datagram(type='trigger', device_id='bogus', timestamp_ns=T0),
    datagram(type='something_else', device_id='tee'),
])
def test_malformed_datagrams_are_ignored(server, data):
    server.arm()
    server._handle_datagram(data, ADDR, T0)
    assert server.state.value == 'armed'


def test_trigger_datagrams_drive_a_measurement(server):
    server.arm()
    for _ in range(3):  # sensors send each trigger several times
        server._handle_datagram(datagram(type='trigger', device_id='tee', timestamp_ns=T0), ADDR, T0)
    for _ in range(3):
        server._handle_datagram(
            datagram(type='trigger', device_id='hog_close', timestamp_ns=T0 + 3 * S), ADDR, T0)
    history = server.get_history()
    assert len(history) == 1
    assert history[0]['tee_to_hog_close_ms'] == pytest.approx(3000)


def test_udp_listener_survives_bad_input(client, server):
    """End to end over a real socket: garbage first, then a valid run."""
    port = server.udp_socket.getsockname()[1]
    server.arm()
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for bad in (b'\xff\xfe', b'[1]', b'{', datagram(type='trigger', device_id=5, timestamp_ns=1)):
            sock.sendto(bad, ('127.0.0.1', port))
        sock.sendto(datagram(type='trigger', device_id='tee', timestamp_ns=T0), ('127.0.0.1', port))
        sock.sendto(datagram(type='trigger', device_id='hog_close', timestamp_ns=T0 + 3 * S),
                    ('127.0.0.1', port))
    finally:
        sock.close()

    deadline = time.time() + 2
    while time.time() < deadline and server.state.value != 'completed':
        time.sleep(0.01)
    assert server._udp_thread.is_alive()
    assert server.state.value == 'completed'


# --- sensor liveness and clock check -------------------------------------------

def heartbeat(server, device_id, offset_ms, delay_ms=2.0):
    """Deliver a heartbeat from a sensor whose clock is offset_ms behind the server's."""
    now_ns = time.time_ns()
    sent_ns = now_ns - int(offset_ms * 1e6)
    server._handle_datagram(
        datagram(type='heartbeat', device_id=device_id, timestamp_ns=sent_ns),
        ADDR, now_ns + int(delay_ms * 1e6))


def sensor(server, device_id):
    return next(s for s in server.get_sensors_status()['sensors'] if s['device_id'] == device_id)


def test_heartbeat_marks_sensor_online_with_good_clock(server):
    heartbeat(server, 'tee', offset_ms=0)
    status = sensor(server, 'tee')
    assert status['status'] == 'online'
    assert status['clock_ok'] is True
    assert status['clock_offset_ms'] == pytest.approx(2.0, abs=0.2)
    assert status['ip'] == ADDR[0]


@pytest.mark.parametrize("offset_ms", [500, -500])
def test_clock_skew_is_flagged(server, offset_ms):
    heartbeat(server, 'hog_far', offset_ms=offset_ms)
    status = sensor(server, 'hog_far')
    assert status['status'] == 'online'
    assert status['clock_ok'] is False


def test_network_delay_spikes_do_not_flag_clock(server):
    for delay_ms in (2, 180, 3, 250):
        heartbeat(server, 'tee', offset_ms=0, delay_ms=delay_ms)
    assert sensor(server, 'tee')['clock_ok'] is True


def test_clock_recovers_after_sync(server):
    for _ in range(3):
        heartbeat(server, 'tee', offset_ms=-400)
    assert sensor(server, 'tee')['clock_ok'] is False
    for _ in range(6):  # old samples age out of the window
        heartbeat(server, 'tee', offset_ms=0)
    assert sensor(server, 'tee')['clock_ok'] is True


def test_sensor_times_out(server):
    heartbeat(server, 'tee', offset_ms=0)
    server.sensor_last_seen['tee']['last_seen_ts'] -= server.sensor_timeout_s + 1
    status = sensor(server, 'tee')
    assert status['status'] == 'offline'
    assert status['clock_ok'] is None


# --- WebSocket -----------------------------------------------------------------

def receive_until(ws, msg_type, predicate=lambda data: True, limit=20):
    for _ in range(limit):
        message = ws.receive_json()
        if message['type'] == msg_type and predicate(message['data']):
            return message['data']
    raise AssertionError(f"no matching {msg_type} message")


def test_websocket_sends_snapshot_on_connect(client):
    with client.websocket_connect('/ws') as ws:
        types = [ws.receive_json()['type'] for _ in range(4)]
    assert types == ['state_update', 'history', 'sensors', 'settings']


def test_websocket_pushes_state_history_and_settings(client, server):
    with client.websocket_connect('/ws') as ws:
        for _ in range(4):
            ws.receive_json()

        ws.send_json({'type': 'arm'})
        receive_until(ws, 'state_update', lambda d: d['state'] == 'armed')

        server.handle_trigger('tee', T0)
        receive_until(ws, 'state_update', lambda d: d['state'] == 'measuring')
        server.handle_trigger('hog_close', T0 + 3 * S)
        receive_until(ws, 'state_update', lambda d: d['state'] == 'completed')
        history = receive_until(ws, 'history')
        assert history[0]['tee_to_hog_close_ms'] == pytest.approx(3000)

        server.handle_trigger('hog_far', T0 + 13 * S)
        history = receive_until(ws, 'history')
        assert history[0]['hog_to_hog_ms'] == pytest.approx(10000)

        client.post('/api/settings', json={'speak_hog_hog': True})
        assert receive_until(ws, 'settings')['speak_hog_hog'] is True

        client.post('/api/clear')
        assert receive_until(ws, 'history') == []


def test_websocket_ignores_garbage(client):
    with client.websocket_connect('/ws') as ws:
        for _ in range(4):
            ws.receive_json()
        ws.send_text('not json')
        ws.send_text('[1, 2]')
        ws.send_json({'type': 'arm'})
        receive_until(ws, 'state_update', lambda d: d['state'] == 'armed')


def test_sensor_status_change_is_pushed(client, server):
    with client.websocket_connect('/ws') as ws:
        for _ in range(4):
            ws.receive_json()
        heartbeat(server, 'tee', offset_ms=0)
        data = receive_until(ws, 'sensors')
        assert data['sensors'][0]['status'] == 'online'


# --- auto-rearm ------------------------------------------------------------------

def test_auto_rearm_after_timeout(client, server, monkeypatch):
    server.settings = Settings(auto_rearm_enabled=True, auto_rearm_after_s=1)
    real_sleep = main.asyncio.sleep
    monkeypatch.setattr(main.asyncio, 'sleep', lambda s: real_sleep(min(s, 0.05)))

    run_stone(server)
    assert server.state.value == 'completed'
    deadline = time.time() + 2
    while time.time() < deadline and server.state.value != 'armed':
        time.sleep(0.01)
    assert server.state.value == 'armed'
