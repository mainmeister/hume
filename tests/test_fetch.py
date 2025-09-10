import unittest
from unittest.mock import patch, MagicMock

import requests
import main


class TestFetchBridgeState(unittest.TestCase):
    @patch('requests.get')
    def test_fetch_success(self, mock_get):
        mresp = MagicMock()
        mresp.json.return_value = {"ok": True}
        mock_get.return_value = mresp

        data = main.fetch_bridge_state("http://1.2.3.4/api/user/", timeout=1.0)
        self.assertEqual(data, {"ok": True})
        mock_get.assert_called_once_with("http://1.2.3.4/api/user/", timeout=1.0)

    @patch('requests.get')
    def test_fetch_invalid_json_raises(self, mock_get):
        mresp = MagicMock()
        mresp.json.side_effect = ValueError("bad json")
        mock_get.return_value = mresp

        with self.assertRaises(ValueError):
            main.fetch_bridge_state("http://1.2.3.4/api/user/", timeout=0.1)

    @patch('requests.get', side_effect=requests.exceptions.Timeout("timeout"))
    def test_fetch_timeout_bubbles(self, mock_get):
        with self.assertRaises(requests.exceptions.RequestException):
            main.fetch_bridge_state("http://1.2.3.4/api/user/", timeout=0.01)


if __name__ == '__main__':
    unittest.main()