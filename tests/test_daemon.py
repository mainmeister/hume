import io
import os
import signal
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import importlib
import main


class TestDaemonMode(unittest.TestCase):
    def setUp(self) -> None:
        importlib.reload(main)

    def _setup_env(self, user: str = "user1", ip: str = "1.2.3.4", daemon: str | None = None):
        env = {
            "HUE_USER_ID": user,
            "HUE_BRIDGE_IP": ip,
            "REQUEST_TIMEOUT": "0.5",
        }
        if daemon is not None:
            env["HUE_DAEMON"] = daemon
        return patch.dict(os.environ, env, clear=True)

    def test_is_daemon_mode_cli_flags(self) -> None:
        self.assertTrue(main.is_daemon_mode(["--daemon"]))
        self.assertTrue(main.is_daemon_mode(["-d"]))
        self.assertTrue(main.is_daemon_mode(["-p"]))
        self.assertTrue(main.is_daemon_mode(["--bulbs", "Living", "-d"]))
        self.assertTrue(main.is_daemon_mode(["--bulbs", "Living", "-p"]))
        self.assertTrue(main.is_daemon_mode(["--daemon", "--bulbs", "Living"]))
        self.assertTrue(main.is_daemon_mode(["-p", "--bulbs", "Living"]))
        self.assertFalse(main.is_daemon_mode([]))
        self.assertFalse(main.is_daemon_mode(["--list"]))

    def test_is_daemon_mode_env_vars(self) -> None:
        with patch.dict(os.environ, {"HUE_DAEMON": "1"}, clear=True):
            self.assertTrue(main.is_daemon_mode([]))
        with patch.dict(os.environ, {"HUE_DAEMON": "true"}, clear=True):
            self.assertTrue(main.is_daemon_mode([]))
        with patch.dict(os.environ, {"HUE_DAEMON": "TRUE"}, clear=True):
            self.assertTrue(main.is_daemon_mode([]))
        with patch.dict(os.environ, {"HUE_DAEMON": "yes"}, clear=True):
            self.assertTrue(main.is_daemon_mode([]))
        with patch.dict(os.environ, {"HUE_DAEMON": "0"}, clear=True):
            self.assertFalse(main.is_daemon_mode([]))
        with patch.dict(os.environ, {"HUE_DAEMON": "false"}, clear=True):
            self.assertFalse(main.is_daemon_mode([]))

    def test_load_config_contains_daemon_setting(self) -> None:
        with self._setup_env(daemon="1"):
            cfg = main.load_config()
            self.assertTrue(cfg.get("daemon"))

        with self._setup_env():
            cfg = main.load_config()
            self.assertFalse(cfg.get("daemon"))

    def test_fork_daemon_process_parent_exits(self) -> None:
        with patch("os.fork", return_value=12345), patch("sys.exit") as mock_exit:
            main.fork_daemon_process()
            mock_exit.assert_called_once_with(0)

    def test_fork_daemon_process_child_prints_pid(self) -> None:
        with patch("os.fork", return_value=0), patch("sys.exit") as mock_exit, patch(
            "os.getpid", return_value=54321
        ), patch("builtins.print") as mock_print:
            pid = main.fork_daemon_process()
            mock_exit.assert_not_called()
            self.assertEqual(pid, 54321)
            mock_print.assert_called_once_with(
                "Daemon process started with PID: 54321", flush=True
            )

    def test_fork_daemon_process_no_fork_attribute(self) -> None:
        orig_fork = getattr(os, "fork", None)
        try:
            if hasattr(os, "fork"):
                delattr(os, "fork")
            with patch("sys.exit") as mock_exit, patch("os.getpid", return_value=99999), patch(
                "builtins.print"
            ) as mock_print:
                pid = main.fork_daemon_process()
                mock_exit.assert_not_called()
                self.assertEqual(pid, 99999)
                mock_print.assert_called_once_with(
                    "Daemon process started with PID: 99999", flush=True
                )
        finally:
            if orig_fork is not None:
                os.fork = orig_fork

    @patch("main.fork_daemon_process")
    @patch("main._wait_for_escape_or_sigint")
    @patch("requests.put")
    @patch("requests.get")
    def test_run_mood_application_daemon_mode_bypasses_tty_escape_wait(
        self, mock_get, mock_put, mock_wait_esc, mock_fork
    ) -> None:
        with self._setup_env(daemon="1"):
            base = "http://1.2.3.4/api/user1"

            def _get_side_effect(url, timeout=None):
                m = MagicMock()
                if url == f"{base}/lights":
                    m.json.return_value = {"1": {"name": "TestBulb", "type": "Extended color light"}}
                elif url == f"{base}/lights/1":
                    m.json.return_value = {"state": {"on": True, "bri": 100, "hue": 1000, "sat": 100}}
                else:
                    m.json.return_value = {}
                return m

            mock_get.side_effect = _get_side_effect
            mock_put.return_value = MagicMock(json=lambda: {})

            stop_event = threading.Event()
            # Set stop_event after short delay to simulate running and then stopping
            threading.Timer(0.1, stop_event.set).start()

            main.run_mood_application(daemon=True, stop_event=stop_event)

            # _wait_for_escape_or_sigint should NOT be called in daemon mode
            mock_wait_esc.assert_not_called()
            mock_fork.assert_called_once()

    @patch("main.fork_daemon_process")
    @patch("requests.put")
    @patch("requests.get")
    def test_run_mood_application_daemon_signals(
        self, mock_get, mock_put, mock_fork
    ) -> None:
        with self._setup_env(daemon="1"):
            base = "http://1.2.3.4/api/user1"

            def _get_side_effect(url, timeout=None):
                m = MagicMock()
                if url == f"{base}/lights":
                    m.json.return_value = {"1": {"name": "TestBulb", "type": "Extended color light"}}
                elif url == f"{base}/lights/1":
                    m.json.return_value = {"state": {"on": True, "bri": 100, "hue": 1000, "sat": 100}}
                else:
                    m.json.return_value = {}
                return m

            mock_get.side_effect = _get_side_effect
            mock_put.return_value = MagicMock(json=lambda: {})

            # Simulate sending SIGTERM to process after 0.1s
            def send_sig():
                time.sleep(0.1)
                os.kill(os.getpid(), signal.SIGTERM)

            t = threading.Thread(target=send_sig, daemon=True)
            t.start()

            # Run in daemon mode on main thread so signal handler catches SIGTERM
            main.run_mood_application(daemon=True)

            # Ensure put was called for bulb restoration
            self.assertGreaterEqual(mock_put.call_count, 1)

    def test_run_mood_application_no_user_id(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # No HUE_USER_ID
            with patch("requests.get") as mock_get:
                main.run_mood_application(daemon=True)
                mock_get.assert_not_called()

    @patch("requests.get")
    def test_run_mood_application_no_bulbs(self, mock_get) -> None:
        with self._setup_env(daemon="1"):
            base = "http://1.2.3.4/api/user1"
            mock_get.return_value = MagicMock(json=lambda: {})  # No lights
            with patch("main.start_mood_thread") as mock_start:
                main.run_mood_application(daemon=True)
                mock_start.assert_not_called()

    @patch("main.fork_daemon_process")
    @patch("main._wait_for_escape_or_sigint")
    @patch("requests.put")
    @patch("requests.get")
    def test_run_mood_application_non_daemon_does_not_fork(
        self, mock_get, mock_put, mock_wait_esc, mock_fork
    ) -> None:
        with self._setup_env():
            base = "http://1.2.3.4/api/user1"

            def _get_side_effect(url, timeout=None):
                m = MagicMock()
                if url == f"{base}/lights":
                    m.json.return_value = {"1": {"name": "TestBulb", "type": "Extended color light"}}
                elif url == f"{base}/lights/1":
                    m.json.return_value = {"state": {"on": True, "bri": 100, "hue": 1000, "sat": 100}}
                else:
                    m.json.return_value = {}
                return m

            mock_get.side_effect = _get_side_effect
            mock_put.return_value = MagicMock(json=lambda: {})

            stop_event = threading.Event()
            threading.Timer(0.1, stop_event.set).start()

            main.run_mood_application(daemon=False, stop_event=stop_event)

            mock_fork.assert_not_called()
            mock_wait_esc.assert_called_once()

    def test_wait_for_signal_or_stop_event_keyboard_interrupt(self) -> None:
        stop_event = threading.Event()
        with patch.object(stop_event, "wait", side_effect=KeyboardInterrupt):
            main._wait_for_signal_or_stop_event(stop_event)
            self.assertTrue(stop_event.is_set())

    def test_wait_for_signal_or_stop_event_non_main_thread(self) -> None:
        stop_event = threading.Event()
        def worker():
            time.sleep(0.05)
            stop_event.set()

        t = threading.Thread(target=worker)
        t.start()
        # Call in non-main thread context
        def thread_target():
            main._wait_for_signal_or_stop_event(stop_event)

        th = threading.Thread(target=thread_target)
        th.start()
        th.join(timeout=2.0)
        t.join(timeout=2.0)
        self.assertFalse(th.is_alive())
        self.assertTrue(stop_event.is_set())

    def test_is_hume_daemon_cmdline(self) -> None:
        self.assertTrue(main._is_hume_daemon_cmdline(["python", "main.py", "--daemon"]))
        self.assertTrue(main._is_hume_daemon_cmdline(["/usr/bin/python3", "/opt/hume/main.py", "-d"]))
        self.assertTrue(main._is_hume_daemon_cmdline(["hume", "-p"]))
        self.assertTrue(main._is_hume_daemon_cmdline(["python", "main.py"]))
        self.assertTrue(main._is_hume_daemon_cmdline(["uv", "run", "python", "main.py", "-d"]))

        # Excluded commands
        self.assertFalse(main._is_hume_daemon_cmdline([]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "-m", "unittest", "discover"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["pytest", "tests/test_daemon.py"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "--help"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "-h"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "--show-daemons"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "-P"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "--pids"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "--kill-daemon"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "-k"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "--list"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["python", "main.py", "-l"]))
        self.assertFalse(main._is_hume_daemon_cmdline(["grep", "main.py"]))

    def test_pid_registration_and_unregistration(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main._get_pid_dir", return_value=tmpdir):
                main._register_daemon_pid(88888)
                pid_file = os.path.join(tmpdir, "88888")
                self.assertTrue(os.path.exists(pid_file))

                main._unregister_daemon_pid(88888)
                self.assertFalse(os.path.exists(pid_file))

    def test_get_running_daemon_pids_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main._get_pid_dir", return_value=tmpdir), patch("os.path.isdir") as mock_isdir:
                def isdir_mock(path):
                    if path == tmpdir:
                        return True
                    if path == "/proc":
                        return False
                    return False
                mock_isdir.side_effect = isdir_mock
                with patch("subprocess.run") as mock_subproc:
                    mock_subproc.return_value = MagicMock(returncode=0, stdout="  PID COMMAND\n")
                    pids = main.get_running_daemon_pids()
                    self.assertEqual(pids, [])

    def test_get_running_daemon_pids_from_registry_and_cleans_stale(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main._get_pid_dir", return_value=tmpdir):
                main._register_daemon_pid(11111)
                main._register_daemon_pid(22222)

                def kill_mock(pid, sig):
                    if pid == 11111:
                        return None
                    raise ProcessLookupError()

                with patch("os.kill", side_effect=kill_mock), patch("os.getpid", return_value=99999), patch("os.path.isdir", side_effect=lambda p: p == tmpdir):
                    pids = main.get_running_daemon_pids()
                    self.assertEqual(pids, [11111])
                    # Stale 22222 should have been cleaned up
                    self.assertFalse(os.path.exists(os.path.join(tmpdir, "22222")))
                    self.assertTrue(os.path.exists(os.path.join(tmpdir, "11111")))

    def test_get_running_daemon_pids_from_proc(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main._get_pid_dir", return_value=tmpdir):
                with patch("os.path.isdir") as mock_isdir:
                    mock_isdir.side_effect = lambda p: p in (tmpdir, "/proc")
                    with patch("os.listdir") as mock_listdir:
                        def listdir_mock(path):
                            if path == tmpdir:
                                return []
                            if path == "/proc":
                                return ["33333", "44444", "cpuinfo", "self"]
                            return []
                        mock_listdir.side_effect = listdir_mock

                        def mock_open_fn(file, mode="r", *args, **kwargs):
                            if file == "/proc/33333/cmdline":
                                return io.BytesIO(b"python\x00main.py\x00-d\x00")
                            if file == "/proc/44444/cmdline":
                                return io.BytesIO(b"python\x00-m\x00unittest\x00discover\x00")
                            raise FileNotFoundError()

                        with patch("builtins.open", side_effect=mock_open_fn):
                            with patch("os.kill", return_value=None), patch("os.getpid", return_value=99999):
                                pids = main.get_running_daemon_pids()
                                self.assertEqual(pids, [33333])

    def test_get_running_daemon_pids_from_ps_fallback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main._get_pid_dir", return_value=tmpdir):
                with patch("os.path.isdir", side_effect=lambda p: p == tmpdir):
                    ps_output = """  PID COMMAND
  12345 python /home/user/hume/main.py --daemon
  12346 python -m unittest discover
  12347 /usr/bin/python3 main.py -p
"""
                    with patch("subprocess.run") as mock_run:
                        mock_run.return_value = MagicMock(returncode=0, stdout=ps_output)
                        with patch("os.kill", return_value=None), patch("os.getpid", return_value=99999):
                            pids = main.get_running_daemon_pids()
                            self.assertEqual(pids, [12345, 12347])

    def test_get_running_daemon_pids_excludes_current_process(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("main._get_pid_dir", return_value=tmpdir):
                main._register_daemon_pid(12345)
                with patch("os.getpid", return_value=12345), patch("os.kill", return_value=None):
                    pids = main.get_running_daemon_pids()
                    self.assertNotIn(12345, pids)

    def test_show_running_daemon_pids_empty(self) -> None:
        with patch("main.get_running_daemon_pids", return_value=[]), patch("builtins.print") as mock_print:
            res = main.show_running_daemon_pids()
            self.assertEqual(res, [])
            mock_print.assert_called_once_with("No running daemon processes found.")

    def test_show_running_daemon_pids_with_entries(self) -> None:
        with patch("main.get_running_daemon_pids", return_value=[1234, 5678]), patch("builtins.print") as mock_print:
            res = main.show_running_daemon_pids()
            self.assertEqual(res, [1234, 5678])
            mock_print.assert_any_call("Currently running daemon processes:")
            mock_print.assert_any_call("  [1] PID 1234")
            mock_print.assert_any_call("  [2] PID 5678")

    def test_kill_daemon_by_pid_success(self) -> None:
        kill_calls = []
        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == 0:
                # After sending signal, process is gone
                raise ProcessLookupError()
            return None

        with patch("os.kill", side_effect=mock_kill), patch("main._unregister_daemon_pid") as mock_unreg:
            success = main.kill_daemon_by_pid(12345)
            self.assertTrue(success)
            self.assertIn((12345, signal.SIGTERM), kill_calls)
            mock_unreg.assert_called_with(12345)

    def test_kill_daemon_by_pid_process_lookup_error_on_sigterm(self) -> None:
        with patch("os.kill", side_effect=ProcessLookupError()), patch("main._unregister_daemon_pid") as mock_unreg:
            success = main.kill_daemon_by_pid(12345)
            self.assertTrue(success)
            mock_unreg.assert_called_with(12345)

    def test_kill_daemon_by_pid_fallback_sigkill(self) -> None:
        kill_calls = []
        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            return None  # Never raises ProcessLookupError

        with patch("os.kill", side_effect=mock_kill), patch("time.sleep"), patch("main._unregister_daemon_pid") as mock_unreg:
            success = main.kill_daemon_by_pid(12345, timeout=0.01)
            self.assertTrue(success)
            self.assertIn((12345, signal.SIGTERM), kill_calls)
            self.assertIn((12345, signal.SIGKILL), kill_calls)
            mock_unreg.assert_called_with(12345)

    def test_kill_daemon_by_pid_os_error_sigterm(self) -> None:
        with patch("os.kill", side_effect=PermissionError("Permission denied")):
            success = main.kill_daemon_by_pid(12345)
            self.assertFalse(success)

    def test_kill_daemon_interactive_no_daemons(self) -> None:
        with patch("main.get_running_daemon_pids", return_value=[]), patch("builtins.print") as mock_print:
            res = main.kill_daemon_interactive()
            self.assertFalse(res)
            mock_print.assert_called_once_with("No running daemon processes found.")

    def test_kill_daemon_interactive_cancel(self) -> None:
        with patch("main.get_running_daemon_pids", return_value=[12345]), patch("builtins.print") as mock_print:
            res = main.kill_daemon_interactive(input_fn=lambda prompt: "q")
            self.assertFalse(res)
            mock_print.assert_any_call("Cancelled. No daemon process was killed.")

    def test_kill_daemon_interactive_eof(self) -> None:
        def mock_input(prompt):
            raise EOFError()

        with patch("main.get_running_daemon_pids", return_value=[12345]), patch("builtins.print") as mock_print:
            res = main.kill_daemon_interactive(input_fn=mock_input)
            self.assertFalse(res)
            mock_print.assert_any_call("\nCancelled.")

    def test_kill_daemon_interactive_valid_index(self) -> None:
        with patch("main.get_running_daemon_pids", return_value=[1234, 5678]), patch("main.kill_daemon_by_pid", return_value=True) as mock_kill, patch("builtins.print") as mock_print:
            res = main.kill_daemon_interactive(input_fn=lambda prompt: "2")
            self.assertTrue(res)
            mock_kill.assert_called_once_with(5678)
            mock_print.assert_any_call("Killed daemon process with PID 5678.")

    def test_kill_daemon_interactive_invalid_then_valid(self) -> None:
        inputs = iter(["abc", "99", "1"])
        with patch("main.get_running_daemon_pids", return_value=[1234]), patch("main.kill_daemon_by_pid", return_value=True) as mock_kill, patch("builtins.print") as mock_print:
            res = main.kill_daemon_interactive(input_fn=lambda prompt: next(inputs))
            self.assertTrue(res)
            mock_kill.assert_called_once_with(1234)
            mock_print.assert_any_call("Invalid input: 'abc'. Please enter a number between 1 and 1 (or 'q' to cancel).")
            mock_print.assert_any_call("Invalid index: 99. Please enter a number between 1 and 1 (or 'q' to cancel).")
            mock_print.assert_any_call("Killed daemon process with PID 1234.")

    def test_kill_daemon_interactive_kill_failed(self) -> None:
        with patch("main.get_running_daemon_pids", return_value=[1234]), patch("main.kill_daemon_by_pid", return_value=False) as mock_kill, patch("builtins.print") as mock_print:
            res = main.kill_daemon_interactive(input_fn=lambda prompt: "1")
            self.assertFalse(res)
            mock_kill.assert_called_once_with(1234)
            mock_print.assert_any_call("Failed to kill daemon process with PID 1234.")

    def test_cli_entrypoint_show_daemons_flag(self) -> None:
        with patch("main.show_running_daemon_pids") as mock_show:
            for flag in ("-P", "--show-daemons", "--pids", "--list-daemons"):
                rc = main.cli_entrypoint([flag])
                self.assertEqual(rc, 0)
            self.assertEqual(mock_show.call_count, 4)

    def test_cli_entrypoint_kill_daemon_flag(self) -> None:
        with patch("main.kill_daemon_interactive") as mock_kill_cli:
            for flag in ("-k", "--kill", "--kill-daemon", "--kill-daemons"):
                rc = main.cli_entrypoint([flag])
                self.assertEqual(rc, 0)
            self.assertEqual(mock_kill_cli.call_count, 4)

    def test_cli_entrypoint_help_flag(self) -> None:
        with patch("builtins.print") as mock_print:
            rc = main.cli_entrypoint(["--help"])
            self.assertEqual(rc, 0)
            help_text = mock_print.call_args[0][0]
            self.assertIn("--show-daemons", help_text)
            self.assertIn("--kill-daemon", help_text)

    def test_cli_entrypoint_list_only(self) -> None:
        with patch("main.main", return_value=0) as mock_main, patch("main.run_mood_application") as mock_mood:
            rc = main.cli_entrypoint(["--list"])
            self.assertEqual(rc, 0)
            mock_main.assert_called_once()
            mock_mood.assert_not_called()

    def test_cli_entrypoint_default_mood(self) -> None:
        with patch("main.main", return_value=0) as mock_main, patch("main.run_mood_application") as mock_mood:
            rc = main.cli_entrypoint([])
            self.assertEqual(rc, 0)
            mock_main.assert_called_once()
            mock_mood.assert_called_once_with(daemon=False)


if __name__ == "__main__":
    unittest.main()
