import sys
import types

import pytest

import ai_usage_monitor.credentials as credentials


def test_credential_storage_and_removal_use_keyring(monkeypatch):
    values = {}
    fake = types.SimpleNamespace()
    fake.errors = types.SimpleNamespace(PasswordDeleteError=type("PasswordDeleteError", (Exception,), {}))
    fake.set_keyring = lambda backend: None
    fake.set_password = lambda service, name, value: values.__setitem__((service, name), value)
    fake.get_password = lambda service, name: values.get((service, name))
    def delete(service, name):
        if (service, name) not in values:
            raise fake.errors.PasswordDeleteError()
        del values[(service, name)]
    fake.delete_password = delete
    monkeypatch.setitem(sys.modules, "keyring", fake)
    monkeypatch.setattr(credentials, "_windows_backend", lambda: object())
    monkeypatch.setattr(credentials.os, "name", "nt")
    monkeypatch.setattr(credentials.getpass, "getpass", lambda prompt: "private-key")

    credentials.set_secret_interactive("openai_admin")
    assert values[("ai-usage-monitor", "openai_admin")] == "private-key"
    assert credentials.get_secret("openai_admin") == "private-key"
    assert credentials.delete_secret("openai_admin") is True
    assert credentials.delete_secret("openai_admin") is False


def test_credential_names_are_allowlisted():
    with pytest.raises(ValueError):
        credentials.get_secret("unknown")


def test_credential_storage_is_windows_only(monkeypatch):
    monkeypatch.setattr(credentials.os, "name", "posix")
    with pytest.raises(RuntimeError, match="Windows"):
        credentials._windows_backend()
