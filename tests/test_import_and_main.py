import os
import importlib
import unittest
from unittest.mock import patch, MagicMock

import main


class TestImportAndMain(unittest.TestCase):
    def test_import_without_env_does_not_raise_or_call_network(self):
        with patch.dict(os.environ, {}, clear=True), patch('requests.get') as mock_get:
            # Reload to simulate fresh import under cleared env
            importlib.reload(main)
            mock_get.assert_not_called()

    def test_main_without_user_id_returns_1_and_no_network(self):
        with patch.dict(os.environ, {}, clear=True), patch('requests.get') as mock_get:
            importlib.reload(main)
            rc = main.main()
            self.assertEqual(rc, 1)
            mock_get.assert_not_called()

    def test_main_success_calls_fetch_and_returns_0(self):
        with patch.dict(
            os.environ,
            {
                'HUE_USER_ID': 'user1234',
                'HUE_BRIDGE_IP': '10.1.2.3',
                'REQUEST_TIMEOUT': '0.5',
                'LOG_LEVEL': 'DEBUG',
            },
            clear=True,
        ), patch('requests.get') as mock_get:
            importlib.reload(main)
            mresp = MagicMock()
            mresp.json.return_value = {'bridge': 'ok'}
            mock_get.return_value = mresp

            rc = main.main()
            self.assertEqual(rc, 0)
            mock_get.assert_called_once_with('http://10.1.2.3/api/user1234/', timeout=0.5)


if __name__ == '__main__':
    unittest.main()