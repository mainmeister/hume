import os
import signal
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


if __name__ == "__main__":
    unittest.main()
