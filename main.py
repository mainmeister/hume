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


def _get_mood_max_seconds(default: float = 30.0) -> float:
    """Determine the max seconds for mood transitions.

    Priority:
    1) Command line: --mood-max-seconds=<float> or --mood-max-seconds <float> or -M <float>
    2) Environment: HUE_MOOD_MAX_SECONDS=<float>
    3) Default: 30.0
    Values are clamped to a minimum of 0.5 seconds.
    """
    # 1) CLI parsing (no side effects at import; only read sys.argv when called)
    argv = sys.argv[1:] if isinstance(sys.argv, list) else []
    value: float | None = None

    def _try_parse(s: str) -> float | None:
        try:
            return float(s)
        except (TypeError, ValueError):
            return None

    # Support --mood-max-seconds=VALUE
    for arg in argv:
        if isinstance(arg, str) and arg.startswith("--mood-max-seconds="):
            cand = _try_parse(arg.split("=", 1)[1])
            if cand is not None:
                value = cand
                break

    # Support --mood-max-seconds VALUE and -M VALUE
    if value is None:
        for i, arg in enumerate(argv):
            if arg == "--mood-max-seconds" and i + 1 < len(argv):
                cand = _try_parse(argv[i + 1])
                if cand is not None:
                    value = cand
                    break
            if arg == "-M" and i + 1 < len(argv):
                cand = _try_parse(argv[i + 1])
                if cand is not None:
                    value = cand
                    break

    # 2) Environment fallback
    if value is None:
        env_raw = os.getenv("HUE_MOOD_MAX_SECONDS")
        if env_raw is not None:
            value = _try_parse(env_raw)

    # 3) Default
    if value is None:
        value = default

    # Clamp to sensible minimum (0.5s)
    if value < 0.5:
        value = 0.5
    return float(value)


def mood(
    bulb_name: str,
    *,
    stop_event: Optional["threading.Event"] = None,
    restore_on_exit: bool = True,
) -> None:
    """Run a real-time random dynamic mood lighting loop for the given bulb name.

    This function is designed to be used as a thread target. It will run indefinitely
    until asked to stop via stop_event. It reads configuration from environment via
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

    # Preserve original state for restoration on exit
    orig_on, orig_bri, orig_hue, orig_sat = is_on, cur_bri, cur_hue, cur_sat

    if not is_on:
        try:
            set_light_state(base_url, light_id, on=True, timeout=timeout)
            is_on = True
        except requests.exceptions.RequestException as e:
            logger.error("Failed to turn on light %s: %s", light_id, e)
            return

    logger.info("Starting mood loop for '%s' (id=%s)", bulb_name, light_id)

    try:
        while True:
            if stop_event is not None and stop_event.is_set():
                break

            # 3. Generate random target color (hue/sat) and brightness
            tgt_hue = random.randint(0, 65535)
            tgt_sat = random.randint(150, 254)
            tgt_bri = random.randint(10, 254)

            # 4. Random transition time between 0.5 seconds and configured max (default 30.0)
            max_seconds = _get_mood_max_seconds(30.0)
            t_seconds = random.uniform(0.5, max_seconds)

            # 5. Number of 0.1s steps
            steps = max(1, int(round(t_seconds / 0.1)))

            # 6-7. Per-step increments
            dhue = (tgt_hue - cur_hue) / steps
            dsat = (tgt_sat - cur_sat) / steps
            dbri = (tgt_bri - cur_bri) / steps

            # 8-9. Loop applying incremental updates
            for i in range(1, steps + 1):
                if stop_event is not None and stop_event.is_set():
                    break
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

            # If we broke early due to stop_event, exit outer loop too
            if stop_event is not None and stop_event.is_set():
                break

            # 10. Repeat with new random target (current already updated)
            # Loop continues
    finally:
        # Attempt to restore original state when exiting the loop
        if restore_on_exit:
            try:
                set_light_state(
                    base_url,
                    light_id,
                    on=bool(orig_on),
                    bri=int(orig_bri),
                    hue=int(orig_hue),
                    sat=int(orig_sat),
                    transitiontime=0,
                    timeout=timeout,
                )
                logger.info("Restored '%s' (id=%s) to original state", bulb_name, light_id)
            except Exception as e:  # broader catch to ensure cleanup path doesn't raise
                logger.warning("Failed to restore original state for light %s: %s", light_id, e)


import threading

def start_mood_thread(bulb_name: str, stop_event: threading.Event | None = None) -> threading.Thread:
    """Start the mood() loop in a daemon thread and return the thread.

    If stop_event is provided, the thread will exit when the event is set and
    the light will be restored to its original state.
    """
    t = threading.Thread(
        target=mood,
        args=(bulb_name,),
        kwargs={"stop_event": stop_event},
        name=f"mood-{bulb_name}",
        daemon=True,
    )
    t.start()
    return t


def _wait_for_escape_or_sigint() -> None:
    """Block until ESC is pressed or a KeyboardInterrupt (Ctrl-C) occurs.

    - On Windows uses msvcrt.kbhit/getwch.
    - On POSIX terminals uses termios/tty with select for non-blocking key reads.
    - If stdin is not a TTY, falls back to waiting for KeyboardInterrupt.
    """
    try:
        # Windows
        if os.name == "nt":
            try:
                import msvcrt  # type: ignore
            except Exception:
                # Fallback: wait for Ctrl-C
                while True:
                    time.sleep(0.2)
            while True:
                if msvcrt.kbhit():
                    ch = msvcrt.getwch()
                    if ch and ord(ch) == 27:  # ESC
                        return
                time.sleep(0.1)
        else:
            # POSIX
            import sys as _sys
            import select as _select
            if not _sys.stdin.isatty():
                # Not a TTY; wait for Ctrl-C
                while True:
                    time.sleep(0.2)
            import termios as _termios
            import tty as _tty
            fd = _sys.stdin.fileno()
            old_settings = _termios.tcgetattr(fd)
            try:
                _tty.setcbreak(fd)
                while True:
                    r, _, _ = _select.select([_sys.stdin], [], [], 0.1)
                    if r:
                        ch = _sys.stdin.read(1)
                        if ch == "\x1b":
                            return
            finally:
                _termios.tcsetattr(fd, _termios.TCSADRAIN, old_settings)
    except KeyboardInterrupt:
        # Respect Ctrl-C everywhere
        return


def run_mood_application() -> None:
    """Start mood threads for predefined bulbs and wait for ESC/Ctrl-C to stop.

    On shutdown, signals all threads to stop and waits for a clean restore of
    original light states.
    """
    bulbs = ["Billy", "Anna", "Sleepy"]
    stop_event = threading.Event()
    threads = []
    for name in bulbs:
        t = start_mood_thread(name, stop_event)
        threads.append(t)
    logger.info("Mood threads started for bulbs: %s", ", ".join(bulbs))
    logger.info("Press ESC (or Ctrl-C) to stop and restore bulbs...")
    _wait_for_escape_or_sigint()
    logger.info("Stopping mood threads and restoring bulbs...")
    stop_event.set()
    # Join threads briefly; they restore on exit
    for t in threads:
        t.join(timeout=10.0)
    logger.info("All mood threads stopped.")


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
    # Start interactive mood application that can be stopped with ESC/Ctrl-C
    run_mood_application()
