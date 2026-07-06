"""
Platform-layer tests: the macOS and Windows paths cannot run in CI (no such
hosts), so every subprocess/filesystem touchpoint is asserted through mocks —
which binary is invoked, with which arguments, and what gets written where.
The Linux path is exercised for real by the client-probe e2e.
"""

import subprocess
import unittest
from pathlib import Path, PureWindowsPath
from unittest import mock

from wg_client import tunnel


def _completed(returncode=0, stdout=""):
    return subprocess.CompletedProcess([], returncode=returncode, stdout=stdout)


class PlatformDetection(unittest.TestCase):
    def test_known_platforms(self):
        for system, expected in (("Linux", "linux"), ("Darwin", "macos"),
                                 ("Windows", "windows")):
            with mock.patch("platform.system", return_value=system):
                self.assertEqual(tunnel._platform(), expected)

    def test_unknown_platform_is_refused(self):
        with mock.patch("platform.system", return_value="Plan9"):
            with self.assertRaises(RuntimeError):
                tunnel._platform()


class MacOSPath(unittest.TestCase):
    """macOS drives wg-quick, with configs under /usr/local/etc/wireguard."""

    def test_conf_dir(self):
        with mock.patch("platform.system", return_value="Darwin"):
            self.assertEqual(tunnel.conf_path("wdg0"),
                             Path("/usr/local/etc/wireguard/wdg0.conf"))

    def test_up_calls_wg_quick_with_conf_path(self):
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("shutil.which", return_value="/usr/local/bin/wg-quick"), \
             mock.patch.object(tunnel, "write_config",
                               return_value=Path("/usr/local/etc/wireguard/wdg0.conf")), \
             mock.patch("subprocess.run", return_value=_completed()) as run:
            tunnel.up("wdg0", "[Interface]\n")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[0], "wg-quick")
        self.assertEqual(cmd[1], "up")
        self.assertTrue(cmd[2].endswith("wdg0.conf"))
        self.assertTrue(run.call_args[1]["check"])

    def test_down_calls_wg_quick_down(self):
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("shutil.which", return_value="wg-quick"), \
             mock.patch("subprocess.run", return_value=_completed()) as run:
            tunnel.down("wdg1")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:2], ["wg-quick", "down"])
        self.assertTrue(cmd[2].endswith("wdg1.conf"))

    def test_missing_wg_quick_is_actionable(self):
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch("shutil.which", return_value=None):
            with self.assertRaises(FileNotFoundError):
                tunnel._find_wg_quick()


class WindowsPath(unittest.TestCase):
    """Windows drives wireguard.exe service installs + the registry toggle."""

    def _win(self):
        return mock.patch("platform.system", return_value="Windows")

    def test_conf_dir_uses_programdata(self):
        with self._win(), mock.patch.dict("os.environ",
                                          {"PROGRAMDATA": r"D:\PD"}):
            # Path() renders backslashes only on Windows; compare the parts.
            self.assertEqual(tunnel.conf_path("wdg0"),
                             Path(r"D:\PD") / "WireGuard" / "wdg0.conf")

    def test_up_installs_tunnel_service_and_sets_registry(self):
        exe = r"C:\Program Files\WireGuard\wireguard.exe"
        with self._win(), \
             mock.patch.object(tunnel, "write_config",
                               return_value=PureWindowsPath(
                                   r"C:\ProgramData\WireGuard\wdg0.conf")), \
             mock.patch.object(tunnel.Path, "exists", return_value=True), \
             mock.patch("subprocess.run", return_value=_completed()) as run:
            tunnel.up("wdg0", "[Interface]\n")

        reg_cmd = run.call_args_list[0][0][0]
        self.assertEqual(reg_cmd[0], "reg")
        self.assertIn("MultipleSimultaneousTunnels", reg_cmd)
        self.assertIn("REG_DWORD", reg_cmd)

        install_cmd = run.call_args_list[1][0][0]
        self.assertEqual(install_cmd[0], exe)
        self.assertEqual(install_cmd[1], "/installtunnel")
        self.assertTrue(str(install_cmd[2]).endswith("wdg0.conf"))

    def test_down_uninstalls_by_tunnel_name(self):
        with self._win(), \
             mock.patch.object(tunnel.Path, "exists", return_value=True), \
             mock.patch("subprocess.run", return_value=_completed()) as run:
            tunnel.down("wdg1")
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[1], "/uninstalltunnel")
        self.assertEqual(cmd[2], "wdg1")  # by NAME, not by conf path

    def test_is_up_reads_service_state(self):
        with self._win(), \
             mock.patch("subprocess.run",
                        return_value=_completed(stdout="STATE: 4 RUNNING")) as run:
            self.assertTrue(tunnel.is_up("wdg0"))
        cmd = run.call_args[0][0]
        self.assertEqual(cmd[:2], ["sc", "query"])
        self.assertEqual(cmd[2], "WireGuardTunnel$wdg0")

    def test_handshake_age_is_none_on_windows(self):
        with self._win():
            self.assertIsNone(tunnel.handshake_age("wdg0"))

    def test_missing_wireguard_exe_is_actionable(self):
        with self._win(), mock.patch.object(tunnel.Path, "exists",
                                            return_value=False):
            with self.assertRaises(FileNotFoundError):
                tunnel._find_wireguard_exe()


class ConfigWriting(unittest.TestCase):
    def test_posix_config_is_chmod_600(self):
        with mock.patch("platform.system", return_value="Darwin"), \
             mock.patch.object(tunnel.Path, "mkdir"), \
             mock.patch.object(tunnel.Path, "write_text") as write, \
             mock.patch.object(tunnel.Path, "chmod") as chmod:
            tunnel.write_config("[Interface]\n", "wdg0")
        write.assert_called_once_with("[Interface]\n")
        chmod.assert_called_once_with(0o600)

    def test_windows_config_skips_chmod(self):
        with mock.patch("platform.system", return_value="Windows"), \
             mock.patch.object(tunnel.Path, "mkdir"), \
             mock.patch.object(tunnel.Path, "write_text"), \
             mock.patch.object(tunnel.Path, "chmod") as chmod:
            tunnel.write_config("[Interface]\n", "wdg0")
        chmod.assert_not_called()


if __name__ == "__main__":
    unittest.main()
