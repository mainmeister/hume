import os
import unittest
from unittest.mock import patch
import importlib

import main


class TestConfig(unittest.TestCase):
    def test_defaults_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=True):
            cfg = main.load_config()
            self.assertIsNone(cfg["user_id"])  # not required at import
            self.assertEqual(cfg["bridge_ip"], "192.168.1.2")
            self.assertEqual(cfg["log_level"], "INFO")
            self.assertEqual(cfg["timeout"], 5.0)

    def test_overrides_and_timeout_parsing(self):
        with patch.dict(
            os.environ,
            {
                "HUE_USER_ID": "abc12345",
                "HUE_BRIDGE_IP": "10.0.0.10",
                "LOG_LEVEL": "DEBUG",
                "REQUEST_TIMEOUT": "7.5",
            },
            clear=True,
        ):
            cfg = main.load_config()
            self.assertEqual(cfg["user_id"], "abc12345")
            self.assertEqual(cfg["bridge_ip"], "10.0.0.10")
            self.assertEqual(cfg["log_level"], "DEBUG")
            self.assertEqual(cfg["timeout"], 7.5)

    def test_invalid_timeout_falls_back(self):
        with patch.dict(os.environ, {"REQUEST_TIMEOUT": "abc"}, clear=True):
            cfg = main.load_config()
            self.assertEqual(cfg["timeout"], 5.0)


if __name__ == '__main__':
    unittest.main()