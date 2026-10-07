import unittest
from typing import Any
import hume


class TestFormatBridgeState(unittest.TestCase):
    def test_format_table_basic(self) -> None:
        headers = ["Col A", "Col B"]
        rows = [["1", "Alpha"], ["2", "Beta"]]
        table = hume.format_table(headers, rows)
        self.assertIn("+-------+-------+", table)
        self.assertIn("| Col A | Col B |", table)
        self.assertIn("| 1     | Alpha |", table)
        self.assertIn("| 2     | Beta  |", table)

    def test_format_table_with_title(self) -> None:
        table = hume.format_table(["Key", "Val"], [["k1", "v1"]], title="Sample Title")
        self.assertIn("=== Sample Title ===", table)
        self.assertIn("| Key | Val |", table)

    def test_format_table_empty(self) -> None:
        self.assertEqual(hume.format_table([], []), "")
        self.assertIn("=== Empty ===", hume.format_table([], [], title="Empty"))

    def test_format_table_variable_row_lengths(self) -> None:
        headers = ["A", "B", "C"]
        rows = [["1"], ["2", "two", "three", "extra"]]
        table = hume.format_table(headers, rows)
        self.assertIn("| 1 ", table)
        self.assertIn("| 2 ", table)

    def test_format_bridge_state_full(self) -> None:
        data = {
            "config": {
                "name": "My Hue Bridge",
                "ipaddress": "192.168.2.19",
                "modelid": "BSB002",
                "bridgeid": "001788FFFE123456",
                "mac": "00:17:88:12:34:56",
                "apiversion": "1.62.0",
                "swversion": "1962097030",
                "zigbeechannel": 25,
                "timezone": "Europe/London",
                "localtime": "2026-10-07T12:00:00",
            },
            "lights": {
                "1": {
                    "name": "Living Room Hue",
                    "type": "Extended color light",
                    "modelid": "LCT015",
                    "state": {
                        "on": True,
                        "bri": 254,
                        "colormode": "hs",
                        "hue": 10000,
                        "sat": 200,
                        "reachable": True,
                    },
                },
                "2": {
                    "name": "Kitchen Ceiling",
                    "type": "Dimmable light",
                    "modelid": "LWB010",
                    "state": {
                        "on": False,
                        "bri": 127,
                        "reachable": False,
                    },
                },
            },
            "groups": {
                "1": {
                    "name": "Living Room",
                    "type": "Room",
                    "lights": ["1"],
                    "state": {"all_on": True, "any_on": True},
                }
            },
            "scenes": {
                "sc1": {
                    "name": "Relax",
                    "type": "GroupScene",
                    "group": "1",
                    "lights": ["1"],
                }
            },
            "sensors": {
                "1": {
                    "name": "Motion Sensor",
                    "type": "ZLLPresence",
                    "modelid": "SML001",
                }
            },
        }

        output = hume.format_bridge_state(data)
        self.assertIn("=== Bridge Configuration ===", output)
        self.assertIn("My Hue Bridge", output)
        self.assertIn("192.168.2.19", output)
        self.assertIn("=== Discovered Lights ===", output)
        self.assertIn("Living Room Hue", output)
        self.assertIn("Extended color light", output)
        self.assertIn("254 (100%)", output)
        self.assertIn("hue:10000 sat:200", output)
        self.assertIn("Kitchen Ceiling", output)
        self.assertIn("127 (50%)", output)
        self.assertIn("=== Groups & Rooms ===", output)
        self.assertIn("Living Room", output)
        self.assertIn("ALL ON", output)
        self.assertIn("=== Scenes ===", output)
        self.assertIn("Relax", output)
        self.assertIn("=== Sensors ===", output)
        self.assertIn("Motion Sensor", output)

    def test_format_bridge_state_light_color_modes(self) -> None:
        lights = {
            "1": {
                "name": "CT Bulb",
                "type": "Color temperature light",
                "state": {"on": True, "bri": 200, "colormode": "ct", "ct": 350, "reachable": True},
            },
            "2": {
                "name": "XY Bulb",
                "type": "Color light",
                "state": {"on": True, "bri": 254, "colormode": "xy", "xy": [0.4, 0.4], "reachable": True},
            },
        }
        output = hume.format_bridge_state({"lights": lights})
        self.assertIn("ct:350", output)
        self.assertIn("xy:[0.4, 0.4]", output)

    def test_format_bridge_state_standalone_lights(self) -> None:
        lights = {
            "1": {
                "name": "Desk Lamp",
                "type": "Extended color light",
                "state": {"on": True, "bri": 254},
            }
        }
        output = hume.format_bridge_state(lights)
        self.assertIn("=== Discovered Lights ===", output)
        self.assertIn("Desk Lamp", output)

    def test_format_bridge_state_generic_dict(self) -> None:
        data = {"bridge": "ok", "version": 2}
        output = hume.format_bridge_state(data)
        self.assertIn("=== Bridge Configuration ===", output)
        self.assertIn("bridge", output)
        self.assertIn("ok", output)

    def test_format_bridge_state_empty_and_primitives(self) -> None:
        self.assertIn("No configuration data returned", hume.format_bridge_state({}))
        self.assertIn("No configuration data returned", hume.format_bridge_state(None))

        list_out = hume.format_bridge_state(["alpha", "beta"])
        self.assertIn("alpha", list_out)
        self.assertIn("beta", list_out)

        scalar_out = hume.format_bridge_state("simple string")
        self.assertIn("simple string", scalar_out)


if __name__ == "__main__":
    unittest.main()
