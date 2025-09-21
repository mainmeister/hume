"""
Minimal Philips Hue control utility entrypoint.

This module avoids side effects at import time. Runtime behavior is gated behind
`if __name__ == "__main__":` and a main() function.

Functions provided:
- load_config(): read environment configuration with defaults and validation
- build_base_url(user_id, bridge_ip): compose Hue base URL
- fetch_bridge_state(base_url, timeout): fetch and return parsed JSON data
- mood(bulb_name): run dynamic mood lighting loop for a given bulb name (thread target)

See docs/plan.md and docs/tasks.md for the improvement plan.
"""

from __future__ import annotations

import json
import logging
import os
import random
import sys
import time
from typing import Any, Dict, Optional

import requests


logger = logging.getLogger(__name__)


def setup_logging(level_str: str | None) -> None:
    level_name = (level_str or "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


def _redact_user_id(user_id: str) -> str:
    if not user_id:
        return "<missing>"
    return f"***{user_id[-4:]}" if len(user_id) > 4 else "***"


def load_config() -> Dict[str, Any]:
    """Load configuration from environment with defaults.

    Returns a dict with keys: user_id (str|None), bridge_ip (str), log_level (str), timeout (float).
    Note: user_id may be None; main() validates and handles errors with messaging.
    """
    user_id = os.getenv("HUE_USER_ID")
    bridge_ip = os.getenv("HUE_BRIDGE_IP", "192.168.1.2")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    timeout_raw = os.getenv("REQUEST_TIMEOUT", "5.0")
    try:
        timeout = float(timeout_raw)
    except ValueError:
        timeout = 5.0
        logger.warning("Invalid REQUEST_TIMEOUT=%s, defaulting to %s", timeout_raw, timeout)

    return {
        "user_id": user_id,
        "bridge_ip": bridge_ip,
        "log_level": log_level,
        "timeout": timeout,
    }


def build_base_url(user_id: str, bridge_ip: str) -> str:
    return f"http://{bridge_ip}/api/{user_id}/"


def fetch_bridge_state(base_url: str, timeout: float = 5.0) -> Any:
    """Fetch the Hue bridge root state and return parsed JSON.

    Raises requests.exceptions.RequestException on network issues and ValueError on JSON decoding.
    """
    resp = requests.get(base_url, timeout=timeout)
    try:
        return resp.json()
    except ValueError as e:
        raise ValueError("Invalid JSON response from Hue Bridge") from e


# --- Hue light helpers (no network at import; functions only) ---

def _endpoint(base_url: str, path: str) -> str:
    if not base_url.endswith('/'):
        base_url = base_url + '/'
    return base_url + path.lstrip('/')


def get_lights(base_url: str, timeout: float = 5.0) -> Dict[str, Any]:
    """Return the lights collection (mapping of id -> light info)."""
    url = _endpoint(base_url, "lights")
    resp = requests.get(url, timeout=timeout)
    return resp.json()


def resolve_light_id_by_name(base_url: str, bulb_name: str, timeout: float = 5.0) -> Optional[str]:
    """Resolve a light id by its human-readable name (case-insensitive)."""
    lights = get_lights(base_url, timeout=timeout)
    # lights is a dict of id -> {"name": ..., ...}
    name_lower = bulb_name.strip().lower()
    for lid, info in (lights or {}).items():
        try:
            if str(info.get("name", "")).strip().lower() == name_lower:
                return str(lid)
        except AttributeError:
            continue
    return None


def get_light_state(base_url: str, light_id: str, timeout: float = 5.0) -> Dict[str, Any]:
    url = _endpoint(base_url, f"lights/{light_id}")
    resp = requests.get(url, timeout=timeout)
    data = resp.json()
    # Expected: {"state": {...}, ...}
    state = data.get("state", {}) if isinstance(data, dict) else {}
    return state


def set_light_state(
    base_url: str,
    light_id: str,
    *,
    on: Optional[bool] = None,
    bri: Optional[int] = None,
    hue: Optional[int] = None,
    sat: Optional[int] = None,
    transitiontime: Optional[int] = None,
    timeout: float = 5.0,
) -> Any:
    """PUT state to a Hue light. transitiontime is in 100ms units if provided."""
    payload: Dict[str, Any] = {}
    if on is not None:
        payload["on"] = bool(on)
    if bri is not None:
        payload["bri"] = int(max(1, min(254, bri)))
    if hue is not None:
        payload["hue"] = int(max(0, min(65535, hue)))
    if sat is not None:
        payload["sat"] = int(max(0, min(254, sat)))
    if transitiontime is not None:
        payload["transitiontime"] = int(max(0, transitiontime))

    url = _endpoint(base_url, f"lights/{light_id}/state")
    resp = requests.put(url, json=payload, timeout=timeout)
    try:
        return resp.json()
    except ValueError:
        return None


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def mood(bulb_name: str) -> None:
    """Run a real-time random dynamic mood lighting loop for the given bulb name.

    This function is designed to be used as a thread target. It will run indefinitely
    until the hosting process stops. It reads configuration from environment via
    load_config() at call time and performs no network at import time.
    """
    cfg = load_config()
    user_id = cfg.get("user_id")
    bridge_ip = cfg.get("bridge_ip")
    timeout = float(cfg.get("timeout", 5.0))

    if not user_id:
        raise RuntimeError("HUE_USER_ID is required to run mood()")

    base_url = build_base_url(user_id, bridge_ip)

    # Resolve light id by name
    try:
        light_id = resolve_light_id_by_name(base_url, bulb_name, timeout=timeout)
    except requests.exceptions.RequestException as e:
        logger.error("Failed to fetch lights from Hue Bridge: %s", e)
        return

    if not light_id:
        logger.error("Light named '%s' not found on the bridge", bulb_name)
        return

    # Ensure the light is on and get its current state
    try:
        state = get_light_state(base_url, light_id, timeout=timeout)
    except requests.exceptions.RequestException as e:
        logger.error("Failed to get state for light %s: %s", light_id, e)
        return

    is_on = bool(state.get("on", False))
    cur_bri = int(state.get("bri", 200))
    cur_hue = int(state.get("hue", 0))
    cur_sat = int(state.get("sat", 200))

    if not is_on:
        try:
            set_light_state(base_url, light_id, on=True, timeout=timeout)
            is_on = True
        except requests.exceptions.RequestException as e:
            logger.error("Failed to turn on light %s: %s", light_id, e)
            return

    logger.info("Starting mood loop for '%s' (id=%s)", bulb_name, light_id)

    while True:
        # 3. Generate random target color (hue/sat) and brightness
        tgt_hue = random.randint(0, 65535)
        tgt_sat = random.randint(150, 254)
        tgt_bri = random.randint(10, 254)

        # 4. Random transition time 0.5-5.0 seconds
        t_seconds = random.uniform(0.5, 30.0)

        # 5. Number of 0.1s steps
        steps = max(1, int(round(t_seconds / 0.1)))

        # 6-7. Per-step increments
        dhue = (tgt_hue - cur_hue) / steps
        dsat = (tgt_sat - cur_sat) / steps
        dbri = (tgt_bri - cur_bri) / steps

        # 8-9. Loop applying incremental updates
        for i in range(1, steps + 1):
            cur_hue = int(_clamp(round(cur_hue + dhue), 0, 65535))
            cur_sat = int(_clamp(round(cur_sat + dsat), 0, 254))
            cur_bri = int(_clamp(round(cur_bri + dbri), 1, 254))
            try:
                set_light_state(
                    base_url,
                    light_id,
                    on=True,
                    bri=cur_bri,
                    hue=cur_hue,
                    sat=cur_sat,
                    # Using bridge-side 100ms transition to smooth micro-steps if desired
                    transitiontime=0,
                    timeout=timeout,
                )
            except requests.exceptions.RequestException as e:
                logger.warning("Transient error setting light state: %s", e)
                # Continue trying next step after sleep
            time.sleep(0.1)

        # 10. Repeat with new random target (current already updated)
        # Loop continues


import threading

def start_mood_thread(bulb_name: str) -> threading.Thread:
    """Start the mood() loop in a daemon thread and return the thread."""
    t = threading.Thread(target=mood, args=(bulb_name,), name=f"mood-{bulb_name}", daemon=True)
    t.start()
    return t


def main() -> int:
    cfg = load_config()

    # Configure logging early
    setup_logging(cfg.get("log_level"))

    user_id = cfg.get("user_id")
    bridge_ip = cfg.get("bridge_ip")
    timeout = float(cfg.get("timeout", 5.0))

    if not user_id:
        logger.error(
            "HUE_USER_ID is not set. Please export HUE_USER_ID before running. See README.md."
        )
        return 1

    redacted_user = _redact_user_id(user_id)
    logger.debug("Effective configuration: bridge_ip=%s, user_id=%s, timeout=%s", bridge_ip, redacted_user, timeout)

    base_url = build_base_url(user_id, bridge_ip)
    logger.info("Fetching Hue bridge state from http://%s/... (base path)", bridge_ip)

    try:
        data = fetch_bridge_state(base_url, timeout=timeout)
        pretty = json.dumps(data, indent=4)
        logger.info("%s", pretty)
        return 0
    except requests.exceptions.RequestException as e:
        logger.error("Network error talking to Hue Bridge at %s: %s", bridge_ip, e)
        return 2
    except ValueError as e:
        logger.error("Failed to parse Hue Bridge response: %s", e)
        return 3


if __name__ == "__main__":
    main()
    start_mood_thread('Billy')
    start_mood_thread('Anna')
    start_mood_thread('Sleepy')
    while True:
        time.sleep(1)
    sys.exit(main())
