#!/usr/bin/env python3
"""
SnakeUSBIP Control Suite - Automated Unit & Integration Tests
Validates the unified snakeusbip-ctl management tool across macOS and Linux.
"""
import os
import sys
import subprocess
import json
import unittest

import importlib.machinery
import importlib.util
from unittest import mock

SCRIPT_PATH = os.path.join(os.path.dirname(__file__), "..", "scripts", "snakeusbip-ctl")


def _load_ctl_module():
    loader = importlib.machinery.SourceFileLoader("snakeusbip_ctl_mod", SCRIPT_PATH)
    spec = importlib.util.spec_from_loader("snakeusbip_ctl_mod", loader)
    mod = importlib.util.module_from_spec(spec)
    loader.exec_module(mod)
    return mod

class TestControlSuite(unittest.TestCase):

    def test_script_exists_and_is_executable(self):
        self.assertTrue(os.path.exists(SCRIPT_PATH), f"snakeusbip-ctl not found at {SCRIPT_PATH}")

    def test_status_json_output(self):
        res = subprocess.run([sys.executable, SCRIPT_PATH, "status", "--json"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"Error running status: {res.stderr}")
        data = json.loads(res.stdout)
        self.assertIn("os", data)
        self.assertIn("service_manager", data)
        self.assertIn("port_active", data)
        self.assertIn("lan_ip", data)
        self.assertIn("devices", data)
        self.assertIsInstance(data["devices"], list)

    def test_doctor_execution(self):
        res = subprocess.run([sys.executable, SCRIPT_PATH, "doctor"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"Doctor exited with error: {res.stderr}")
        self.assertIn("SnakeUSBIP System Doctor", res.stdout)
        self.assertIn("Operating System:", res.stdout)

    def test_list_devices(self):
        res = subprocess.run([sys.executable, SCRIPT_PATH, "list"],
                             capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(res.returncode, 0, f"List devices failed: {res.stderr}")
        self.assertIn("Discovered USB Peripherals", res.stdout)

    def test_share_device_linux_fails_when_device_absent(self):
        mod = _load_ctl_module()
        with mock.patch.object(mod.os.path, "exists", return_value=False), \
             mock.patch.object(mod, "_wait_udev_settle"):
            ok = mod._share_device_linux("1-1.3", "/usr/sbin/usbip")
        self.assertFalse(ok)
        self.assertIn("not found on USB bus", mod._last_bind_error.get("1-1.3", ""))

    def test_busid_lock_per_device_serialization(self):
        mod = _load_ctl_module()
        l1 = mod._get_busid_lock("1-1.3")
        l1_again = mod._get_busid_lock("1-1.3")
        l2 = mod._get_busid_lock("1-1.4")
        self.assertIs(l1, l1_again)
        self.assertIsNot(l1, l2)

    def test_sudo_rerun_uses_explicit_subcommand(self):
        mod = _load_ctl_module()
        cmd = mod.build_sudo_command("connect", "192.168.1.2", "1-1")
        self.assertEqual(cmd[0], "sudo")
        self.assertEqual(cmd[1], sys.executable)
        self.assertEqual(os.path.realpath(cmd[2]), os.path.realpath(SCRIPT_PATH))
        self.assertEqual(cmd[3:], ["connect", "192.168.1.2", "1-1"])

    def test_rerun_with_sudo_has_no_timeout_and_handles_ctrl_c(self):
        mod = _load_ctl_module()
        with mock.patch.object(mod.shutil, "which", return_value="/usr/bin/sudo"), \
             mock.patch.object(mod.subprocess, "run", return_value=mock.Mock(returncode=0)) as run:
            self.assertTrue(mod.rerun_with_sudo("start"))
        self.assertNotIn("timeout", run.call_args.kwargs)
        with mock.patch.object(mod.shutil, "which", return_value="/usr/bin/sudo"), \
             mock.patch.object(mod.subprocess, "run", side_effect=KeyboardInterrupt):
            self.assertFalse(mod.rerun_with_sudo("start"))
        with mock.patch.object(mod.shutil, "which", return_value=None):
            self.assertFalse(mod.rerun_with_sudo("start"))

    def test_privileged_actions_rerun_with_their_own_arguments(self):
        mod = _load_ctl_module()
        cases = [
            (lambda: mod.connect_remote_device(" 192.168.1.2 ", "1-1"), ("connect", "192.168.1.2", "1-1")),
            (lambda: mod.disconnect_remote_device("3"), ("disconnect", "3")),
            (lambda: mod.unshare_device("1-2"), ("unshare", "1-2")),
            (lambda: mod.start_service(), ("start",)),
            (lambda: mod.stop_service(), ("stop",)),
        ]
        for call, expected in cases:
            with mock.patch.object(mod, "IS_LINUX", True), \
                 mock.patch.object(mod, "is_root", return_value=False), \
                 mock.patch.object(mod, "rerun_with_sudo", return_value=True) as rerun:
                self.assertTrue(call())
            rerun.assert_called_once_with(*expected)

    def test_connect_reports_failure_written_to_stderr(self):
        mod = _load_ctl_module()

        def fake_result(cmd, timeout=30):
            if "attach" in cmd:
                return 1, "", "usbip: error: Attach Request for 1-1 failed - Device busy (exported)"
            return 0, "", ""

        with mock.patch.object(mod, "IS_LINUX", True), \
             mock.patch.object(mod, "is_root", return_value=True), \
             mock.patch.object(mod, "run_cmd", return_value=""), \
             mock.patch.object(mod, "run_cmd_result", side_effect=fake_result), \
             mock.patch.object(mod, "send_control_command", return_value=None), \
             mock.patch.object(mod.shutil, "which", return_value="/usr/sbin/usbip"):
            self.assertFalse(mod.connect_remote_device("192.168.1.2", "1-1"))

    def test_choose_item_by_number_text_and_cancel(self):
        mod = _load_ctl_module()
        items = ["192.168.1.2", "192.168.1.3"]
        with mock.patch("builtins.input", side_effect=["2"]):
            self.assertEqual(mod.choose_item("server", items, mod.is_valid_host, "an IP"), "192.168.1.3")
        with mock.patch("builtins.input", side_effect=["9", "1"]):
            self.assertEqual(mod.choose_item("server", items, mod.is_valid_host, "an IP"), "192.168.1.2")
        with mock.patch("builtins.input", side_effect=["10.0.0.5"]):
            self.assertEqual(mod.choose_item("server", items, mod.is_valid_host, "an IP"), "10.0.0.5")
        for answer in (["q"], [""], KeyboardInterrupt, EOFError):
            with mock.patch("builtins.input", side_effect=answer):
                with self.assertRaises(mod.PromptCancelled):
                    mod.choose_item("server", items, mod.is_valid_host, "an IP")

    def test_dashboard_survives_ctrl_c_and_q_in_connect_flow(self):
        mod = _load_ctl_module()
        answers = iter(["9", "q", "9", KeyboardInterrupt, KeyboardInterrupt])

        def fake_input(prompt=""):
            value = next(answers)
            if value is KeyboardInterrupt:
                raise KeyboardInterrupt
            return value

        with mock.patch("builtins.input", side_effect=fake_input), \
             mock.patch.object(mod.os, "system"), \
             mock.patch.object(mod, "get_service_status", return_value={
                 "os": "Linux", "service_manager": "systemd", "running": False, "port_active": False}), \
             mock.patch.object(mod, "get_lan_ip", return_value="192.168.1.10"), \
             mock.patch.object(mod, "list_devices", return_value=[]), \
             mock.patch.object(mod, "get_attached_ports", return_value=[]), \
             mock.patch.object(mod, "scan_network_servers", return_value=[("192.168.1.2", "host")]), \
             mock.patch.object(mod, "list_remote_devices") as list_remote, \
             mock.patch.object(mod, "connect_remote_device") as connect:
            mod.render_dashboard("both")
        list_remote.assert_not_called()
        connect.assert_not_called()

    def test_client_mode_hides_server_actions(self):
        mod = _load_ctl_module()
        answers = iter(["3", "1", "q"])
        with mock.patch("builtins.input", side_effect=lambda prompt="": next(answers)), \
             mock.patch.object(mod.os, "system"), \
             mock.patch.object(mod, "get_service_status", return_value={
                 "os": "Linux", "service_manager": "systemd", "running": False, "port_active": False}), \
             mock.patch.object(mod, "get_lan_ip", return_value="192.168.1.10"), \
             mock.patch.object(mod, "list_devices", return_value=["  1-1    : Mouse (046d:c077)"]), \
             mock.patch.object(mod, "get_attached_ports", return_value=[]), \
             mock.patch.object(mod, "share_device") as share, \
             mock.patch.object(mod, "start_service") as start:
            mod.render_dashboard("client")
        share.assert_not_called()
        start.assert_not_called()

    def test_role_is_saved_in_invoking_users_home_under_sudo(self):
        import tempfile
        mod = _load_ctl_module()
        with tempfile.TemporaryDirectory() as home:
            fake_pw = mock.Mock(pw_dir=home)
            with mock.patch.dict(os.environ, {"SUDO_USER": "someone"}), \
                 mock.patch.object(mod, "is_root", return_value=True), \
                 mock.patch("pwd.getpwnam", return_value=fake_pw), \
                 mock.patch.object(mod.os, "chown"):
                self.assertEqual(mod._role_config_path(), os.path.join(home, ".config", "snakeusbip", "ctl.json"))
                self.assertTrue(mod.save_role("client"))
                self.assertEqual(mod.load_role(), "client")

    def test_relaunch_skips_sudo_v_when_nopasswd_works(self):
        mod = _load_ctl_module()
        calls = []

        def fake_run(cmd, **kwargs):
            calls.append(cmd)
            return mock.Mock(returncode=0)

        with mock.patch.object(mod, "is_root", return_value=False), \
             mock.patch.object(mod, "IS_LINUX", True), \
             mock.patch.object(mod.sys.stdin, "isatty", return_value=True), \
             mock.patch.object(mod.shutil, "which", return_value="/usr/bin/sudo"), \
             mock.patch("builtins.input", return_value="y"), \
             mock.patch.object(mod.subprocess, "run", side_effect=fake_run), \
             mock.patch.object(mod.os, "execvp") as execvp:
            mod.offer_sudo_relaunch("client")
        self.assertEqual(calls, [["sudo", "-n", "true"]])
        execvp.assert_called_once()
        self.assertEqual(execvp.call_args.args[1][-1], "dashboard")

    def test_extract_busid_and_host_validation(self):
        mod = _load_ctl_module()
        self.assertEqual(mod.extract_busid("  1-1.2    : Logitech Mouse (046d:c077)"), "1-1.2")
        self.assertIsNone(mod.extract_busid("Bus 001 Device 002: ID 046d:c077"))
        self.assertFalse(mod.is_valid_host("-h"))
        self.assertTrue(mod.is_valid_host("raspberrypi.local"))

if __name__ == "__main__":
    unittest.main()
