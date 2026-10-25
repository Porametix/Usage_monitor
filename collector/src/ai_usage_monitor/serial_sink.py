from __future__ import annotations

import logging
from typing import Callable

import serial

from .models import UsageSnapshot
from .serial_protocol import serialize_snapshot

LOG = logging.getLogger(__name__)


class SerialSink:
    """One-way USB Serial writer. Opening a port also prevents competing collectors."""

    def __init__(self, port: str, *, serial_factory: Callable[..., serial.Serial] = serial.Serial):
        self.port = port
        self._factory = serial_factory
        self._serial: serial.Serial | None = None

    @property
    def connected(self) -> bool:
        return self._serial is not None and bool(self._serial.is_open)

    def connect(self) -> bool:
        if self.connected:
            return True
        try:
            self._serial = self._factory(self.port, 115200, timeout=0, write_timeout=2)
            LOG.info("Serial connected: %s", self.port)
            return True
        except (serial.SerialException, OSError):
            self._serial = None
            LOG.warning("Serial unavailable; will retry: %s", self.port)
            return False

    def send(self, snapshot: UsageSnapshot) -> bool:
        if not self.connected and not self.connect():
            return False
        assert self._serial is not None
        data = serialize_snapshot(snapshot)
        try:
            written = self._serial.write(data)
            self._serial.flush()
            if written != len(data):
                raise serial.SerialTimeoutException("short write")
            return True
        except (serial.SerialException, OSError):
            self.close()
            LOG.warning("Serial disconnected; will retry: %s", self.port)
            return False

    def close(self) -> None:
        if self._serial is not None:
            try:
                self._serial.close()
            except (serial.SerialException, OSError):
                pass
            self._serial = None
