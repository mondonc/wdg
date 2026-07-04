import json
import os
from pathlib import Path

import keyring

KEYRING_SERVICE = "wg-client"
KEYRING_PRIVATE_KEY = "wg_private_key"


def _config_path() -> Path:
    if os.name == "nt":
        base = Path(os.environ.get("APPDATA", Path.home()))
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "wg-client" / "config.json"


def load() -> dict:
    path = _config_path()
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def save(data: dict):
    path = _config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def get_private_key() -> str | None:
    return keyring.get_password(KEYRING_SERVICE, KEYRING_PRIVATE_KEY)


def set_private_key(key: str):
    keyring.set_password(KEYRING_SERVICE, KEYRING_PRIVATE_KEY, key)


# --- Runtime state: which tunnels are currently up ---------------------------

def _state_path() -> Path:
    return _config_path().parent / "tunnels.json"


def load_tunnels() -> list[dict]:
    path = _state_path()
    if not path.exists():
        return []
    return json.loads(path.read_text())


def save_tunnels(states: list[dict]):
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(states, indent=2))


def clear_tunnels():
    _state_path().unlink(missing_ok=True)
