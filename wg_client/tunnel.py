import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from wg_client.i18n import _


def _platform() -> str:
    s = platform.system()
    if s == "Linux":
        return "linux"
    if s == "Darwin":
        return "macos"
    if s == "Windows":
        return "windows"
    raise RuntimeError(f"Unsupported platform: {s}")


def _conf_path() -> Path:
    p = _platform()
    if p == "linux":
        return Path("/etc/wireguard/wg-client.conf")
    if p == "macos":
        return Path("/usr/local/etc/wireguard/wg-client.conf")
    if p == "windows":
        return Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "WireGuard" / "wg-client.conf"


def _tunnel_name() -> str:
    return "wg-client"


def write_config(conf: str) -> Path:
    path = _conf_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(conf)
    if _platform() != "windows":
        path.chmod(0o600)
    return path


def _find_wg_quick() -> str:
    for candidate in ["wg-quick", "/usr/bin/wg-quick", "/usr/local/bin/wg-quick"]:
        if shutil.which(candidate):
            return candidate
    raise FileNotFoundError(
        _("wg-quick not found. Install wireguard-tools (Linux/macOS).")
    )


def _find_wireguard_exe() -> str:
    candidates = [
        r"C:\Program Files\WireGuard\wireguard.exe",
        r"C:\Program Files (x86)\WireGuard\wireguard.exe",
    ]
    for c in candidates:
        if Path(c).exists():
            return c
    raise FileNotFoundError(
        _("wireguard.exe not found. Install the official WireGuard client.")
    )


def connect(conf: str):
    path = write_config(conf)
    p = _platform()

    if p in ("linux", "macos"):
        bin_ = _find_wg_quick()
        subprocess.run([bin_, "up", str(path)], check=True)

    elif p == "windows":
        exe = _find_wireguard_exe()
        subprocess.run([exe, "/installtunnel", str(path)], check=True)


def disconnect():
    p = _platform()
    path = _conf_path()

    if p in ("linux", "macos"):
        bin_ = _find_wg_quick()
        subprocess.run([bin_, "down", str(path)], check=True)

    elif p == "windows":
        exe = _find_wireguard_exe()
        subprocess.run([exe, "/removetunnel", _tunnel_name()], check=True)


def status() -> bool:
    """Returns True if the tunnel interface appears to be up."""
    p = _platform()
    try:
        if p in ("linux", "macos"):
            result = subprocess.run(
                ["wg", "show", _tunnel_name()],
                capture_output=True,
            )
            return result.returncode == 0

        elif p == "windows":
            result = subprocess.run(
                ["sc", "query", f"WireGuardTunnel${_tunnel_name()}"],
                capture_output=True,
                text=True,
            )
            return "RUNNING" in result.stdout
    except FileNotFoundError:
        return False
