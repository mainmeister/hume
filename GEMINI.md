# Gemini Agent Interaction Guide for `hume`

This document provides guidelines for a Gemini agent to interact with the `hume` project, a minimal Philips Hue control utility.

## Project Overview

`hume` is a Python-based utility for controlling Philips Hue lights. Its primary features are:

1.  **Bridge State Discovery**: It can fetch and display the configuration of a Hue bridge.
2.  **Dynamic Mood Lighting**: It can run a continuous, randomized mood lighting effect on one or more Hue bulbs.

The project is designed to be robust and testable, with a clear separation between configuration, networking, and application logic. It avoids side-effects on import, making it safe to be imported by other modules.

## Core Commands and Usage

The main entrypoint is `hume.py`. It can be executed using `uv run python hume.py`.

### Prerequisites

- The `HUE_USER_ID` environment variable **must** be set to a valid Hue bridge user ID.
- The `HUE_BRIDGE_IP` environment variable can be set to the IP address of the Hue bridge. If not set, it defaults to `192.168.2.19`.

### Displaying Bridge Configuration

To fetch and display the Hue bridge's configuration without starting the mood lighting, use the `--list` (or `-l`) flag.

**Command:**
```bash
uv run python hume.py --list
```

This will print formatted ASCII tables/grids with the bridge configuration, discovered lights, groups, and devices, and then exit.

### Managing Daemon Processes

- **Display running daemon PIDs**:
  ```bash
  uv run python hume.py --show-daemons
  # or: uv run python hume.py -P
  ```
- **List running daemons and kill interactively by index**:
  ```bash
  uv run python hume.py --kill-daemon
  # or: uv run python hume.py -k
  ```

### Running the Mood Lighting Application

To start the interactive mood lighting application, run the script without the `--list` flag.

**Command:**
```bash
uv run python hume.py
```

This will:
1.  First, print the bridge configuration.
2.  Then, start the mood lighting on selected bulbs.
3.  The application will run until it is stopped by pressing `ESC` or `Ctrl-C`.

## Mood Lighting Control

The mood lighting feature runs in background threads, one for each selected bulb.

### Bulb Selection

The bulbs to be used for mood lighting are selected with the following precedence:

1.  **Command-line argument**: `--bulbs "Living Room,Kitchen"` or `-b "Living Room,Kitchen"`
2.  **Environment variable**: `export HUE_MOOD_BULBS="Living Room,Kitchen"`
3.  **Automatic discovery**: If neither of the above is provided, the application will discover all bulbs of type "Extended color light" on the bridge and use them.

### Behavior

- The mood lighting loop for each bulb runs in a separate thread.
- The loop continuously changes the bulb's color, brightness, and saturation.
- The transitions are randomized.
- If a bulb is off, it will be turned on.
- When the application is stopped, the bulbs are restored to their original state (on/off, color, and brightness).

### Programmatic Control

The `hume.py` script also provides functions for programmatic control of the mood lighting:

- `start_mood_thread(bulb_name: str, stop_event: threading.Event | None = None) -> threading.Thread`: Starts a mood lighting thread for a specific bulb.
- `mood(bulb_name: str, *, stop_event: Optional["threading.Event"] = None, restore_on_exit: bool = True)`: The target function for the mood lighting thread.

This allows for more advanced integrations where the mood lighting can be controlled from another script.

## Project Architecture

- **Configuration**: Configuration is loaded from environment variables (`HUE_USER_ID`, `HUE_BRIDGE_IP`, `LOG_LEVEL`, etc.) via the `load_config()` function.
- **Networking**: All HTTP requests to the Hue bridge are made using the `requests` library. Network calls are centralized and include timeouts to prevent hangs.
- **Modularity**: The code is organized into functions with clear responsibilities (e.g., `build_base_url`, `fetch_bridge_state`, `get_lights`).
- **Testability**: The project includes a suite of unit tests in the `tests/` directory. Network calls are mocked to ensure that tests are fast and reliable. Integration tests that require a real Hue bridge are opt-in.

## Interacting with the Project

As a Gemini agent, you can:

- **Read and understand the code**: The code is well-documented and follows modern Python best practices.
- **Execute commands**: You can use the `run_shell_command` tool to execute the `uv run python hume.py` command with different arguments.
- **Modify the code**: You can use the `replace` or `write_file` tools to modify the code, for example, to change the default configuration or add new features.
- **Run tests**: You can run the test suite to verify that your changes have not introduced any regressions.