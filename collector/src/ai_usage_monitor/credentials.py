from __future__ import annotations

import getpass
import os

SERVICE_NAME = "ai-usage-monitor"
_ALLOWED = {"openai_admin"}


def _windows_backend():
    if os.name != "nt":
        raise RuntimeError("Credential storage is supported only through Windows Credential Manager")
    try:
        from keyring.backends.Windows import WinVaultKeyring
    except ImportError as exc:
        raise RuntimeError("Windows Credential Manager backend is unavailable") from exc
    return WinVaultKeyring()


def get_secret(name: str) -> str | None:
    if name not in _ALLOWED:
        raise ValueError("unsupported credential name")
    import keyring
    keyring.set_keyring(_windows_backend())
    return keyring.get_password(SERVICE_NAME, name)


def set_secret_interactive(name: str) -> None:
    if name not in _ALLOWED:
        raise ValueError("unsupported credential name")
    secret = getpass.getpass("OpenAI organization Admin API key (input hidden): ").strip()
    if not secret:
        raise ValueError("empty key was not stored")
    import keyring
    keyring.set_keyring(_windows_backend())
    keyring.set_password(SERVICE_NAME, name, secret)
    del secret


def delete_secret(name: str) -> bool:
    if name not in _ALLOWED:
        raise ValueError("unsupported credential name")
    import keyring
    keyring.set_keyring(_windows_backend())
    try:
        keyring.delete_password(SERVICE_NAME, name)
        return True
    except keyring.errors.PasswordDeleteError:
        return False
