import os
import unittest

import requests

import main


@unittest.skipUnless(os.getenv("INTEGRATION") == "1", "requires integration env")
class TestIntegration(unittest.TestCase):
    def test_fetch_bridge_root_real_bridge(self):
        user_id = os.getenv("HUE_USER_ID")
        bridge_ip = os.getenv("HUE_BRIDGE_IP", "192.168.1.2")
        timeout = float(os.getenv("REQUEST_TIMEOUT", "5.0"))
        self.assertIsNotNone(user_id, "HUE_USER_ID must be set for integration test")

        base_url = main.build_base_url(user_id, bridge_ip)
        try:
            data = main.fetch_bridge_state(base_url, timeout=timeout)
        except requests.exceptions.RequestException as e:
            self.fail(f"Network error during integration test: {e}")
        self.assertIsInstance(data, (dict, list))


if __name__ == '__main__':
    unittest.main()