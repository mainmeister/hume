import unittest

import importlib

class TestBuildBaseUrl(unittest.TestCase):
    def setUp(self):
        # Ensure we import the latest main module
        self.main = importlib.import_module('main')

    def test_build_base_url(self):
        url = self.main.build_base_url("user1234", "10.0.0.2")
        self.assertEqual(url, "http://10.0.0.2/api/user1234/")

    def test_build_base_url_with_ip_like(self):
        # Accepts strings; no validation here by design
        url = self.main.build_base_url("abc", "192.168.1.2")
        self.assertEqual(url, "http://192.168.1.2/api/abc/")

if __name__ == '__main__':
    unittest.main()