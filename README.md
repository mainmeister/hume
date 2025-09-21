# hume

Minimal Philips Hue control utility (work-in-progress).

This project starts as a single-script prototype and evolves into a minimal, testable utility with proper configuration, logging, and tests.

## Quickstart

Prerequisites:
- Python 3.12+
- uv (dependency manager)

Install uv:
- Linux/macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
- Windows (PowerShell): `iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex`

Set up the environment and install locked dependencies:

```bash
uv sync
```

Run the script directly without a global install:

```bash
# Required at runtime
export HUE_USER_ID="<your-registered-user-id>"

# Optional (defaults to 192.168.1.2)
export HUE_BRIDGE_IP="192.168.1.2"

# Optional logging level (DEBUG, INFO, WARNING, ERROR)
export LOG_LEVEL="INFO"

# Optional request timeout (seconds)
export REQUEST_TIMEOUT="5"

uv run python main.py
```

Note: Network calls happen only when executed as a script (not at import). A timeout is always applied to prevent hangs when the bridge is unreachable.

## Environment Variables

- HUE_USER_ID (required at runtime)
  - The Hue bridge user name/token. Do not commit this to version control.
- HUE_BRIDGE_IP (optional; default: `192.168.1.2`)
  - IP address of your Hue Bridge.
- LOG_LEVEL (optional; default: `INFO`)
  - Standard Python logging level.
- REQUEST_TIMEOUT (optional; default: `5.0`)
  - Timeout (in seconds) for network requests.
- HUE_MOOD_MAX_SECONDS (optional; default: `30.0`)
  - Maximum transition duration used by mood lighting when picking a random duration.

## Testing

Run all tests using Python’s unittest:

```bash
uv run python -m unittest discover -s tests -v
```

Integration tests are skipped by default. To enable them (requires a reachable Hue Bridge and correct env vars):

```bash
INTEGRATION=1 uv run python -m unittest discover -s tests -v
```

## Troubleshooting

- Missing HUE_USER_ID: Set `HUE_USER_ID` and re-run. Example: `export HUE_USER_ID=...`
- Timeouts or connection errors: Verify `HUE_BRIDGE_IP` and network connectivity; adjust `REQUEST_TIMEOUT` if necessary.
- Logging verbosity: Set `LOG_LEVEL=DEBUG` to see detailed diagnostics.

## Mood Lighting

Start a real-time random dynamic mood loop for a light by name (runs in a daemon thread):

```bash
uv run python - <<'PY'
import os, time, main
os.environ.setdefault("HUE_USER_ID", "<your-user-id>")
os.environ.setdefault("HUE_BRIDGE_IP", "192.168.1.2")
main.setup_logging("INFO")
# Start the mood thread for the light named "Living Room"
t = main.start_mood_thread("Living Room")
# Let it run for a minute (thread continues until process exits)
time.sleep(60)
PY
```

- Configure logging and timeouts via the same env vars described above.
- Control the maximum random transition duration for mood lighting via either:
  - Environment: `export HUE_MOOD_MAX_SECONDS=10.0`
  - CLI flag: `uv run python main.py --mood-max-seconds 10.0` (or `-M 10.0`)
- Ensure the bridge is reachable; each request uses a timeout to prevent hangs.

## Development
This project will create a real time random dynamic mood lighting based 
on the hue color bulbs.
A method named mood will be created that will run as a thread.
A single argument will be passed which is the name of the bulb.
1. If the bulb is currently off then turn it on.
2. Get the current color and brightness of the bulb.
3. Generate a random color and brightness.
4. Generate a random transition time between 0.5 and 30 seonds.
5. Calculate the number of 0.1 second steps to get to the new color.
6. Calculate the increment in brightness for each step.
7. Calculate the increment in color for each step.
8. Loop through the number of steps and set the new color and brightness.
9. Sleep for 0.1 seconds.
10. Repeat.