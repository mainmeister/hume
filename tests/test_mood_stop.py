import os
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

import importlib
import main


class TestMoodStop(unittest.TestCase):
    def setUp(self) -> None:
        # Ensure we reload main in case prior tests changed module state
        importlib.reload(main)

    def _setup_env(self, user: str="user1", ip: str="1.2.3.4"):
        return patch.dict(os.environ, {"HUE_USER_ID": user, "HUE_BRIDGE_IP": ip, "REQUEST_TIMEOUT": "0.5"}, clear=True)

    def _make_get_side_effect(self, user: str="user1", ip: str="1.2.3.4", orig_state=None):
        if orig_state is None:
            orig_state = {"on": True, "bri": 123, "hue": 40000, "sat": 200}
        base = f"http://{ip}/api/{user}"

        def _side_effect(url, timeout=None):
            m = MagicMock()
            if url == f"{base}/lights":
                m.json.return_value = {"42": {"name": "TestBulb"}}
            elif url == f"{base}/lights/42":
                m.json.return_value = {"state": orig_state}
            else:
                m.json.return_value = {}
            return m

        return _side_effect

    @patch("requests.put")
    @patch("requests.get")
    def test_mood_thread_stops_and_restores_when_original_on(self, mock_get, mock_put) -> None:
        with self._setup_env():
            importlib.reload(main)
            orig = {"on": True, "bri": 123, "hue": 40000, "sat": 200}
            mock_get.side_effect = self._make_get_side_effect(orig_state=orig)
            mock_put.return_value = MagicMock(json=lambda: {})

            stop_event = threading.Event()
            t = main.start_mood_thread("TestBulb", stop_event)
            # Let it do some work
            time.sleep(0.2)
            stop_event.set()
            t.join(timeout=2.0)

            self.assertFalse(t.is_alive(), "mood thread did not stop in time")
            self.assertGreaterEqual(mock_put.call_count, 1)
            last_call = mock_put.call_args
            # Verify final restore payload contains original values
            payload = last_call.kwargs.get("json")
            self.assertIsInstance(payload, dict)
            self.assertEqual(payload.get("on"), True)
            self.assertEqual(payload.get("bri"), 123)
            self.assertEqual(payload.get("hue"), 40000)
            self.assertEqual(payload.get("sat"), 200)

    @patch("requests.put")
    @patch("requests.get")
    def test_mood_thread_restores_to_off_when_original_off(self, mock_get, mock_put) -> None:
        with self._setup_env():
            importlib.reload(main)
            orig = {"on": False, "bri": 50, "hue": 1000, "sat": 100}
            mock_get.side_effect = self._make_get_side_effect(orig_state=orig)
            mock_put.return_value = MagicMock(json=lambda: {})

            stop_event = threading.Event()
            t = main.start_mood_thread("TestBulb", stop_event)
            time.sleep(0.2)
            stop_event.set()
            t.join(timeout=2.0)

            last_call = mock_put.call_args
            payload = last_call.kwargs.get("json")
            self.assertIsInstance(payload, dict)
            self.assertEqual(payload.get("on"), False)
            # Color/brightness may be set alongside off to preserve future on-state
            self.assertEqual(payload.get("bri"), 50)
            self.assertEqual(payload.get("hue"), 1000)
            self.assertEqual(payload.get("sat"), 100)


if __name__ == "__main__":
    unittest.main()
