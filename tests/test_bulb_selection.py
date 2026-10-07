import os
import sys
import unittest
from unittest.mock import patch

import main


class TestBulbSelection(unittest.TestCase):
    def test_default_only_extended_color_lights_sorted_by_id(self) -> None:
        # No CLI or env: should fetch lights and return only Extended color light names sorted by id
        fake_lights = {
            "3": {"name": "C", "type": "Extended color light"},
            "1": {"name": "A", "type": "Extended color light"},
            "2": {"name": "B", "type": "Dimmable light"},
        }
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(main, 'get_lights', return_value=fake_lights) as mock_get_lights:
            names = main.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1)
            self.assertEqual(names, ["A", "C"])  # filtered and sorted by id
            mock_get_lights.assert_called_once()

    def test_env_overrides_without_network(self) -> None:
        with patch.dict(os.environ, {"HUE_MOOD_BULBS": "X, Y, , Z"}, clear=True), \
             patch.object(main, 'get_lights') as mock_get_lights:
            names = main.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1)
            self.assertEqual(names, ["X", "Y", "Z"])  # parsed and trimmed
            mock_get_lights.assert_not_called()

    def test_cli_parsing_variants(self) -> None:
        # Directly test CLI parser helper to avoid mutating global sys.argv too much
        self.assertEqual(main._get_cli_bulb_names(["--bulbs=Kitchen, Hall"]), ["Kitchen", "Hall"])
        self.assertEqual(main._get_cli_bulb_names(["--bulbs", "A,B,C"]), ["A", "B", "C"])
        self.assertEqual(main._get_cli_bulb_names(["-b", " X , Y "]), ["X", "Y"])  # trims
        self.assertIsNone(main._get_cli_bulb_names(["--other", "thing"]))

    def test_cli_precedence_over_env(self) -> None:
        with patch.dict(os.environ, {"HUE_MOOD_BULBS": "EnvOnly"}, clear=True), \
             patch.object(main, 'get_lights') as mock_get_lights, \
             patch.object(sys, 'argv', ["prog", "--bulbs", "CLI1,CLI2" ]):
            names = main.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1)
            self.assertEqual(names, ["CLI1", "CLI2"])  # CLI wins
            mock_get_lights.assert_not_called()


if __name__ == '__main__':
    unittest.main()
