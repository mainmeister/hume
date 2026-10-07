import os
import importlib
import unittest
from unittest.mock import patch, MagicMock

import hume


class TestImportAndMain(unittest.TestCase):
    def test_import_without_env_does_not_raise_or_call_network(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch('requests.get') as mock_get:
            # Reload to simulate fresh import under cleared env
            importlib.reload(hume)
            mock_get.assert_not_called()

    def test_main_without_user_id_returns_1_and_no_network(self) -> None:
        with patch.dict(os.environ, {}, clear=True), patch('requests.get') as mock_get:
            importlib.reload(hume)
            rc = hume.main()
            self.assertEqual(rc, 1)
            mock_get.assert_not_called()

    def test_main_success_calls_fetch_and_returns_0(self) -> None:
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
            importlib.reload(hume)
            mresp = MagicMock()
            mresp.json.return_value = {'bridge': 'ok'}
            mock_get.return_value = mresp

            rc = hume.main()
            self.assertEqual(rc, 0)
            mock_get.assert_called_once_with('http://10.1.2.3/api/user1234/', timeout=0.5)

    def test_main_does_not_show_config_by_default(self) -> None:
        with patch.dict(
            os.environ,
            {
                'HUE_USER_ID': 'user1234',
                'HUE_BRIDGE_IP': '10.1.2.3',
            },
            clear=True,
        ):
            importlib.reload(hume)
            with patch('requests.get') as mock_get, patch('hume.format_bridge_state') as mock_format:
                mresp = MagicMock()
                mresp.json.return_value = {'bridge': 'ok'}
                mock_get.return_value = mresp

                rc = hume.main()
                self.assertEqual(rc, 0)
                mock_format.assert_not_called()

    def test_main_shows_config_when_show_config_is_true(self) -> None:
        with patch.dict(
            os.environ,
            {
                'HUE_USER_ID': 'user1234',
                'HUE_BRIDGE_IP': '10.1.2.3',
            },
            clear=True,
        ):
            importlib.reload(hume)
            with patch('requests.get') as mock_get, patch('hume.format_bridge_state', return_value="FORMATTED_CONFIG") as mock_format, patch('hume.logger.info') as mock_log:
                mresp = MagicMock()
                mresp.json.return_value = {'bridge': 'ok'}
                mock_get.return_value = mresp

                rc = hume.main(show_config=True)
                self.assertEqual(rc, 0)
                mock_format.assert_called_once_with({'bridge': 'ok'})
                mock_log.assert_any_call("\n%s", "FORMATTED_CONFIG")


if __name__ == '__main__':
    unittest.main()