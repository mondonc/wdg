"""
Platform layer for WireGuard tunnels (Linux/macOS via wg-quick, Windows via
the official client's service installer). Every function takes the tunnel
*name* — the client runs several tunnels at once (wdg0, wdg1, …).
"""

import os
import platform
import shutil
import subprocess
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


def _conf_dir() -> Path:
    p = _platform()
    if p == "linux":
        return Path("/etc/wireguard")
    if p == "macos":
        return Path("/usr/local/etc/wireguard")
    return Path(os.environ.get("PROGRAMDATA", "C:\\ProgramData")) / "WireGuard"


def conf_path(name: str) -> Path:
    return _conf_dir() / f"{name}.conf"


def write_config(conf: str, name: str) -> Path:
    path = conf_path(name)
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


def ensure_windows_multitunnel():
    """
    The official Windows client only activates one tunnel unless the
    MultipleSimultaneousTunnels registry value is set. Best effort (needs
    admin — the tunnel installation needs it anyway).
    """
    subprocess.run(
        ["reg", "add", r"HKLM\Software\WireGuard",
         "/v", "MultipleSimultaneousTunnels", "/t", "REG_DWORD", "/d", "1", "/f"],
        capture_output=True,
    )


def wireguard_available() -> bool:
    """Is the platform's WireGuard tooling present?"""
    p = _platform()
    if p in ("linux", "macos"):
        try:
            _find_wg_quick()
            return True
        except FileNotFoundError:
            return False
    try:
        _find_wireguard_exe()
        return True
    except FileNotFoundError:
        return False


def bundled_windows_installer() -> Path | None:
    """
    The all-in-one Windows build ships the official WireGuard MSI next to
    the executable (see `make build-clients`); locate it when frozen.
    """
    import sys

    if _platform() != "windows":
        return None
    base = Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    for candidate in (base, Path(sys.executable).parent):
        msi = candidate / "wireguard-installer.msi"
        if msi.exists():
            return msi
    return None


def install_windows_wireguard() -> bool:
    """Silently install the bundled official MSI (needs admin). Best effort."""
    msi = bundled_windows_installer()
    if msi is None:
        return False
    subprocess.run(
        ["msiexec", "/i", str(msi), "/qn", "/norestart"], capture_output=True
    )
    return wireguard_available()


def install_hint() -> str:
    """Per-platform guidance when WireGuard is missing (no bundled installer)."""
    p = _platform()
    if p == "linux":
        return _("WireGuard is missing. Install it with your distribution "
                 "(e.g. 'sudo apt install wireguard').")
    if p == "macos":
        return _("WireGuard is missing. Install wireguard-tools "
                 "(e.g. 'brew install wireguard-tools').")
    return _("WireGuard is missing. Install the official WireGuard client "
             "from https://www.wireguard.com/install/.")


def up(name: str, conf: str):
    path = write_config(conf, name)
    p = _platform()
    if p in ("linux", "macos"):
        subprocess.run([_find_wg_quick(), "up", str(path)], check=True)
    else:
        ensure_windows_multitunnel()
        subprocess.run([_find_wireguard_exe(), "/installtunnel", str(path)], check=True)


def down(name: str):
    p = _platform()
    if p in ("linux", "macos"):
        subprocess.run([_find_wg_quick(), "down", str(conf_path(name))], check=True)
    else:
        subprocess.run([_find_wireguard_exe(), "/uninstalltunnel", name], check=True)


def is_up(name: str) -> bool:
    p = _platform()
    try:
        if p in ("linux", "macos"):
            return subprocess.run(["wg", "show", name], capture_output=True).returncode == 0
        result = subprocess.run(
            ["sc", "query", f"WireGuardTunnel${name}"], capture_output=True, text=True
        )
        return "RUNNING" in result.stdout
    except FileNotFoundError:
        return False


def handshake_age(name: str) -> float | None:
    """
    Seconds since the tunnel's most recent WireGuard handshake, or None if
    no handshake happened (or it cannot be read — e.g. Windows, where the
    service state from :func:`is_up` is the best signal available).
    """
    if _platform() == "windows":
        return None
    result = subprocess.run(
        ["wg", "show", name, "latest-handshakes"], capture_output=True, text=True
    )
    if result.returncode != 0:
        return None
    latest = 0
    for line in result.stdout.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].isdigit():
            latest = max(latest, int(parts[1]))
    if latest == 0:
        return None
    import time

    return max(0.0, time.time() - latest)
