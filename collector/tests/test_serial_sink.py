import serial

from ai_usage_monitor.aggregator import demo_snapshot
from ai_usage_monitor.serial_sink import SerialSink


class FakeSerial:
    is_open = True
    def __init__(self):
        self.data = b""
        self.closed = False
    def write(self, value):
        self.data += value
        return len(value)
    def flush(self):
        pass
    def close(self):
        self.closed = True
        self.is_open = False


def test_serial_sink_retries_connection_and_sends_one_way_frame():
    instance = FakeSerial()
    calls = 0
    def factory(*args, **kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise serial.SerialException("not connected")
        return instance
    sink = SerialSink("COM3", serial_factory=factory)
    assert sink.send(demo_snapshot(snapshot_id=10)) is False
    assert sink.send(demo_snapshot(snapshot_id=11)) is True
    assert instance.data.endswith(b"\n")
    assert b"Demo" in instance.data
    sink.close()
    assert instance.closed


def test_serial_sink_closes_after_disconnection():
    class Broken(FakeSerial):
        def write(self, value):
            raise serial.SerialException("disconnected")
    instance = Broken()
    sink = SerialSink("COM9", serial_factory=lambda *a, **k: instance)
    assert sink.send(demo_snapshot(snapshot_id=12)) is False
    assert instance.closed
