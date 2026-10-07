# hume

`hume` is a minimal, modular Python utility for interacting with a Philips Hue bridge and running dynamic, real-time mood lighting loops across Hue color bulbs.

---

## Table of Contents

- [Overview](#overview)
- [Requirements & Tech Stack](#requirements--tech-stack)
- [Installation & Setup](#installation--setup)
- [Configuration & Environment Variables](#configuration--environment-variables)
- [Usage & CLI Options](#usage--cli-options)
  - [CLI Flags](#cli-flags)
  - [Example Commands](#example-commands)
  - [Programmatic Usage](#programmatic-usage)
- [Mood Lighting Logic](#mood-lighting-logic)
  - [How It Works](#how-it-works)
  - [Graceful Shutdown & State Restoration](#graceful-shutdown--state-restoration)
- [Testing](#testing)
  - [Running Unit Tests](#running-unit-tests)
  - [Running Integration Tests](#running-integration-tests)
- [Project Structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [License](#license)

---

## Overview

`hume` provides a clean, testable interface to:
1. **Bridge State Inspection**: Fetch and format root configuration and light states from a local Philips Hue Bridge.
2. **Dynamic Mood Lighting**: Run multithreaded, randomized color and brightness transitions across selected bulbs (defaulting to all discovered "Extended color light" devices).
3. **Safe Teardown**: Automatically preserve initial bulb states and restore them upon cooperative shutdown via `ESC`, `Ctrl-C`, or a `threading.Event`.

The codebase is built with zero import-time network side-effects, explicit timeouts, and robust error handling.

---

## Requirements & Tech Stack

- **Language**: Python `>=3.12`
- **Package & Dependency Manager**: [`uv`](https://docs.astral.sh/uv/) (with locked dependencies in `uv.lock`)
- **Key Dependencies**:
  - `requests >= 2.32.4` (HTTP communication with Hue Bridge REST API)
  - `huesdk >= 1.8`
- **Testing**: Python standard library `unittest` (mocked HTTP layer, no live hardware required for unit tests)

---

## Installation & Setup

1. **Install `uv`** (if not already installed):
   - **Linux / macOS**:
     ```bash
     curl -LsSf https://astral.sh/uv/install.sh | sh
     ```
   - **Windows (PowerShell)**:
     ```powershell
     iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex
     ```

2. **Clone the repository and sync dependencies**:
   ```bash
   git clone <repository-url>
   cd hume
   uv sync
   ```

3. **Managing Dependencies**:
   - Add a dependency: `uv add <package>`
   - Update lockfile: `uv lock`

---

## Configuration & Environment Variables

Configuration is loaded dynamically at runtime via `hume.load_config()` with fallback defaults:

| Variable | Required | Default | Description |
|---|---|---|---|
| `HUE_USER_ID` | **Yes** (at runtime) | `None` | Authorized Hue Bridge API username/token. Never commit or log in full (auto-redacted in logs). |
| `HUE_BRIDGE_IP` | No | `192.168.2.19` | IP address or hostname of the Philips Hue Bridge. |
| `LOG_LEVEL` | No | `INFO` | Logging verbosity (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `REQUEST_TIMEOUT` | No | `5.0` | Timeout in seconds for HTTP requests to prevent network hangs. |
| `HUE_MOOD_MAX_SECONDS` | No | `30.0` | Upper bound in seconds for random transition durations (clamped to min 0.5s). |
| `HUE_MOOD_BULBS` | No | Discovered color bulbs | Comma-separated list of bulb names to target for mood lighting. |
| `HUE_DAEMON` | No | `0` | Set to `1` or `true` to run mood lighting in non-interactive daemon mode. |
| `INTEGRATION` | No | `0` | Set to `1` to run live-hardware integration tests against a reachable bridge. |

**Precedence Order**: CLI Options > Environment Variables > Bridge Defaults.

---

## Usage & CLI Options

The primary entry point is `hume.py`.

### CLI Flags

```text
Usage: python hume.py [options]

Options:
  -h, --help                  Show help message and exit
  -l, --list                  Fetch and display Hue bridge configuration, then exit
  -d, -p, --daemon            Run in non-interactive daemon mode (wait for SIGTERM/SIGINT)
  -P, --show-daemons, --pids  Display all currently running daemon PIDs and exit
  -k, --kill, --kill-daemon   List running daemon PIDs and prompt to kill one by index
  -M SEC, --mood-max-seconds SEC
                              Maximum transition duration for mood lighting
                              (default via HUE_MOOD_MAX_SECONDS)
  -b NAMES, --bulbs NAMES     Comma-separated bulb names for mood lighting
                              (default via HUE_MOOD_BULBS)
```

### Example Commands

- **Fetch bridge state and start interactive mood lighting**:
  ```bash
  export HUE_USER_ID="<your-user-id>"
  uv run python hume.py
  ```

- **Run in non-interactive daemon mode (forks to background and outputs PID/task ID)**:
  ```bash
  export HUE_USER_ID="<your-user-id>"
  uv run python hume.py -p
  # or: uv run python hume.py --daemon
  ```

- **Display all currently running daemon PIDs**:
  ```bash
  uv run python hume.py --show-daemons
  # or: uv run python hume.py -P
  # or: uv run python hume.py --pids
  ```

- **List running daemons and interactively select one to kill**:
  ```bash
  uv run python hume.py --kill-daemon
  # or: uv run python hume.py -k
  # or: uv run python hume.py --kill
  ```

- **List bridge state only (no mood lighting started)**:
  ```bash
  export HUE_USER_ID="<your-user-id>"
  uv run python hume.py --list
  ```

- **Target specific bulbs with custom transition limits**:
  ```bash
  export HUE_USER_ID="<your-user-id>"
  uv run python hume.py --bulbs "Living Room,Bedroom" --mood-max-seconds 15.0
  ```

- **Debug logging and custom bridge IP**:
  ```bash
  export HUE_USER_ID="<your-user-id>"
  export HUE_BRIDGE_IP="192.168.1.50"
  export LOG_LEVEL="DEBUG"
  uv run python hume.py
  ```

### Programmatic Usage

You can import `hume` into your own scripts without triggering network operations on import:

```python
import os
import threading
import time
import hume

os.environ["HUE_USER_ID"] = "<your-user-id>"
os.environ["HUE_BRIDGE_IP"] = "192.168.2.19"
hume.setup_logging("INFO")

# Create a stop event for cooperative shutdown
stop_event = threading.Event()

# Start background mood thread for a specific light
thread = hume.start_mood_thread("Living Room", stop_event=stop_event)

try:
    # Let mood loop run for 30 seconds
    time.sleep(30)
finally:
    # Stop thread and restore initial bulb state
    stop_event.set()
    thread.join(timeout=10.0)
```

---

## Mood Lighting Logic

### How It Works

For each targeted bulb, `hume.mood()` executes an asynchronous loop in a dedicated daemon thread:

1. **Discovery & Validation**: Looks up the bulb's light ID by name.
2. **Initial State Capture**: Records the current on/off, brightness (`bri`), hue (`hue`), and saturation (`sat`) state for restoration on exit.
3. **Power On**: If the bulb is currently off, turns it on.
4. **Target Generation**: Randomly generates a new target hue (`0–65535`), saturation (`0–254`), and brightness (`1–254`).
5. **Duration & Step Calculation**: Randomly picks a transition time between 0.5s and `mood_max_seconds` (default 30.0s), dividing the transition into discrete `0.1s` increments.
6. **Smooth Transition**: Incrementally applies intermediate color and brightness changes every 0.1 seconds.
7. **Repeat**: Loops continuously until signaled to stop.

### Graceful Shutdown & State Restoration

When running the interactive application, pressing **`ESC`** (or **`Ctrl-C`**) signals all mood threads to break out of their loops. Each thread catches the exit signal and restores the bulb to its exact initial power, brightness, and color settings before terminating.

---

## Testing

The project uses Python's standard `unittest` framework with full isolation: unit tests never perform live network requests.

### Running Unit Tests

Run all unit tests in verbose mode:

```bash
uv run python -m unittest discover -s tests -v
```

Run a specific test suite or test case:

```bash
uv run python -m unittest tests.test_config -v
uv run python -m unittest tests.test_config.TestConfig.test_defaults_when_env_missing -v
```

### Running Integration Tests

Integration tests run against a physical or simulated Hue Bridge on your network. They are skipped by default and require `INTEGRATION=1`:

```bash
INTEGRATION=1 HUE_USER_ID="<your-user-id>" HUE_BRIDGE_IP="192.168.2.19" uv run python -m unittest discover -s tests -v
```

---

## Project Structure

```text
hume/
├── hume.py                     # Application entry point, CLI parser, Hue API and mood lighting logic
├── pyproject.toml              # Project metadata, Python version requirement, and dependencies
├── uv.lock                     # Locked dependency graph
├── CONTRIBUTING.md             # Contribution guidelines and coding conventions
├── GEMINI.md                   # AI agent reference documentation
├── README.md                   # Main documentation
├── docs/
│   ├── plan.md                 # Architectural design and implementation plan
│   └── tasks.md                # Task tracking and development roadmap
└── tests/
    ├── test_bulb_selection.py  # Tests for CLI/env bulb filtering and precedence
    ├── test_config.py          # Tests for environment variable loading and validation
    ├── test_daemon.py          # Tests for daemon mode and PID management
    ├── test_fetch.py           # Tests for bridge state fetching and JSON parsing
    ├── test_format.py          # Tests for bridge state and table/grid formatting
    ├── test_import_and_main.py # Tests ensuring safe imports and main entry point behavior
    ├── test_integration.py     # Opt-in tests against live Hue Bridge hardware
    ├── test_mood_stop.py       # Tests for mood loop graceful stop and state restoration
    └── test_url.py             # Tests for Hue REST API URL normalization
```

---

## Troubleshooting

- **Missing `HUE_USER_ID`**:
  Ensure `HUE_USER_ID` is exported in your environment. `hume` will log an error and exit with code `1` if it is missing when running the main application.
  ```bash
  export HUE_USER_ID="<your-token>"
  ```
- **Connection timeouts or network errors**:
  Verify your Hue Bridge IP address (`HUE_BRIDGE_IP`) and ensure your device is on the same local subnet. Adjust `REQUEST_TIMEOUT` if your bridge is on a slow network.
- **Bulb not found**:
  Verify the exact name of your light as registered in the Philips Hue app. Use `uv run python hume.py --list` to inspect all light names currently discovered on the bridge.
- **Verbose logs**:
  Set `export LOG_LEVEL=DEBUG` for detailed logging of configuration, endpoints, and step transitions.

---

## License

<!-- TODO: Specify project license (e.g., MIT, Apache-2.0, or proprietary) -->
This project is currently unlicensed. Please add a `LICENSE` file before distributing publicly.
