import os
import sys
import unittest
from unittest.mock import patch

import hume


class TestBulbSelection(unittest.TestCase):
    def test_default_without_bulbs_or_all_flag_returns_empty(self) -> None:
        # No CLI or env: should not fetch lights from bridge and return empty list
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(hume, 'get_lights') as mock_get_lights, \
             patch.object(sys, 'argv', ["hume.py"]):
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1)
            self.assertEqual(names, [])
            mock_get_lights.assert_not_called()

    def test_all_flag_discovers_extended_color_lights_sorted_by_id(self) -> None:
        # With --all flag: should fetch lights and return only Extended color light names sorted by id
        fake_lights = {
            "3": {"name": "C", "type": "Extended color light"},
            "1": {"name": "A", "type": "Extended color light"},
            "2": {"name": "B", "type": "Dimmable light"},
        }
        with patch.dict(os.environ, {}, clear=True), \
             patch.object(hume, 'get_lights', return_value=fake_lights) as mock_get_lights:
            # Test with --all
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1, argv=["--all"])
            self.assertEqual(names, ["A", "C"])  # filtered and sorted by id
            mock_get_lights.assert_called_once()

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(hume, 'get_lights', return_value=fake_lights) as mock_get_lights:
            # Test with -a
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1, argv=["-a"])
            self.assertEqual(names, ["A", "C"])
            mock_get_lights.assert_called_once()

        with patch.dict(os.environ, {}, clear=True), \
             patch.object(hume, 'get_lights', return_value=fake_lights) as mock_get_lights:
            # Test with use_all=True
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1, use_all=True)
            self.assertEqual(names, ["A", "C"])
            mock_get_lights.assert_called_once()

    def test_env_overrides_without_network(self) -> None:
        with patch.dict(os.environ, {"HUE_MOOD_BULBS": "X, Y, , Z"}, clear=True), \
             patch.object(hume, 'get_lights') as mock_get_lights:
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1, argv=[])
            self.assertEqual(names, ["X", "Y", "Z"])  # parsed and trimmed
            mock_get_lights.assert_not_called()

    def test_cli_parsing_variants(self) -> None:
        # Directly test CLI parser helper to avoid mutating global sys.argv too much
        self.assertEqual(hume._get_cli_bulb_names(["--bulbs=Kitchen, Hall"]), ["Kitchen", "Hall"])
        self.assertEqual(hume._get_cli_bulb_names(["--bulbs", "A,B,C"]), ["A", "B", "C"])
        self.assertEqual(hume._get_cli_bulb_names(["-b", " X , Y "]), ["X", "Y"])  # trims
        self.assertIsNone(hume._get_cli_bulb_names(["--other", "thing"]))
        self.assertTrue(hume._is_all_bulbs_flag(["--all"]))
        self.assertTrue(hume._is_all_bulbs_flag(["-a"]))
        self.assertTrue(hume._is_all_bulbs_flag(["-a", "--daemon"]))
        self.assertFalse(hume._is_all_bulbs_flag([]))
        self.assertFalse(hume._is_all_bulbs_flag(["--bulbs", "Kitchen"]))

    def test_cli_precedence_over_all_and_env(self) -> None:
        with patch.dict(os.environ, {"HUE_MOOD_BULBS": "EnvOnly"}, clear=True), \
             patch.object(hume, 'get_lights') as mock_get_lights, \
             patch.object(sys, 'argv', ["prog", "--bulbs", "CLI1,CLI2", "--all"]):
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1)
            self.assertEqual(names, ["CLI1", "CLI2"])  # CLI --bulbs wins over --all and env
            mock_get_lights.assert_not_called()

    def test_all_flag_precedence_over_env(self) -> None:
        fake_lights = {
            "1": {"name": "Discovered1", "type": "Extended color light"},
        }
        with patch.dict(os.environ, {"HUE_MOOD_BULBS": "EnvOnly"}, clear=True), \
             patch.object(hume, 'get_lights', return_value=fake_lights) as mock_get_lights, \
             patch.object(sys, 'argv', ["prog", "--all"]):
            names = hume.get_mood_bulb_names("http://bridge/api/user/", timeout=0.1)
            self.assertEqual(names, ["Discovered1"])  # --all wins over env
            mock_get_lights.assert_called_once()


if __name__ == '__main__':
    unittest.main()
