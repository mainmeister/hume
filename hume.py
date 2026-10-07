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
import shlex
import signal
import subprocess
import sys
import tempfile
import threading
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


def is_daemon_mode(argv: list[str] | None = None) -> bool:
    """Check if daemon mode is enabled via CLI flags (-d, -p, --daemon) or HUE_DAEMON env var."""
    if argv is None:
        argv = sys.argv[1:] if isinstance(sys.argv, list) else []

    if any(arg in ("-d", "-p", "--daemon") for arg in argv):
        return True

    env_val = os.getenv("HUE_DAEMON", "").strip().lower()
    return env_val in ("1", "true", "yes", "y", "t", "on")


def _get_pid_dir() -> str:
    pid_dir = os.path.join(tempfile.gettempdir(), ".hume_pids")
    try:
        os.makedirs(pid_dir, exist_ok=True)
    except OSError:
        pass
    return pid_dir


def _format_options_from_args(args: list[str]) -> str:
    """Format a list of CLI argument strings into a clean shell-quoted options string."""
    if not args:
        return ""
    return shlex.join(args)


def _extract_options_from_cmdline(args: list[str]) -> str:
    """Extract CLI options from a process argument list."""
    if not args:
        return ""

    script_idx = -1
    for idx, arg in enumerate(args):
        base = os.path.basename(arg)
        if base in ("hume.py", "main.py") or arg in ("hume.py", "main.py", "./hume.py", "./main.py"):
            script_idx = idx
            break
        if base == "hume" or arg == "hume":
            script_idx = idx
            break
        if arg == "-m" and idx + 1 < len(args) and os.path.basename(args[idx + 1]) in ("hume", "main"):
            script_idx = idx + 1
            break

    if script_idx != -1:
        opts_args = args[script_idx + 1:]
    else:
        if args and args[0].startswith("-"):
            opts_args = args
        else:
            opts_args = []

    return _format_options_from_args(opts_args)


def _register_daemon_pid(
    pid: int,
    options: str | None = None,
    args: list[str] | None = None,
) -> None:
    try:
        pid_dir = _get_pid_dir()
        pid_file = os.path.join(pid_dir, str(pid))
        if options is None:
            if args is not None:
                options = _format_options_from_args(args)
            else:
                options = ""
        payload = {
            "pid": pid,
            "options": options,
            "args": args if args is not None else [],
        }
        with open(pid_file, "w", encoding="utf-8") as f:
            json.dump(payload, f)
    except OSError:
        pass


def get_daemon_options(pid: int) -> str:
    """Retrieve the command line options associated with a running daemon process."""
    # 1. Check PID directory
    pid_dir = _get_pid_dir()
    pid_file = os.path.join(pid_dir, str(pid))
    if os.path.exists(pid_file):
        try:
            with open(pid_file, "r", encoding="utf-8") as f:
                content = f.read().strip()
            if content:
                try:
                    data = json.loads(content)
                    if isinstance(data, dict):
                        if data.get("options"):
                            return str(data["options"]).strip()
                        if data.get("args"):
                            return _format_options_from_args(data["args"])
                except json.JSONDecodeError:
                    # Stored as plain text / legacy format
                    lines = [line.strip() for line in content.splitlines() if line.strip()]
                    if len(lines) >= 2:
                        return lines[1]
        except (OSError, IOError):
            pass

    # 2. Check /proc on Linux
    if os.path.isdir("/proc"):
        cmdline_file = f"/proc/{pid}/cmdline"
        try:
            with open(cmdline_file, "rb") as f:
                raw = f.read()
            args = [
                arg.decode("utf-8", errors="replace")
                for arg in raw.split(b"\x00")
                if arg
            ]
            opts = _extract_options_from_cmdline(args)
            if opts:
                return opts
        except (OSError, IOError, PermissionError):
            pass

    # 3. Fallback to ps command
    try:
        proc = subprocess.run(
            ["ps", "-p", str(pid), "-o", "args="],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            raw_out = proc.stdout.strip()
            try:
                args = shlex.split(raw_out)
            except ValueError:
                args = raw_out.split()
            opts = _extract_options_from_cmdline(args)
            if opts:
                return opts
    except (OSError, subprocess.SubprocessError):
        pass

    return ""


def format_daemon_process_entry(idx: int, pid: int, options: str | None = None) -> str:
    """Format a daemon process entry with its index, PID, and command-line options."""
    if options is None:
        options = get_daemon_options(pid)
    opts_str = options.strip() if options and options.strip() else "none"
    return f"  [{idx}] PID {pid} (options: {opts_str})"


def _unregister_daemon_pid(pid: int) -> None:
    try:
        pid_dir = _get_pid_dir()
        pid_file = os.path.join(pid_dir, str(pid))
        if os.path.exists(pid_file):
            os.remove(pid_file)
    except OSError:
        pass


def _is_hume_daemon_cmdline(args: list[str], pid: int | None = None) -> bool:
    """Check if command-line arguments correspond to a running hume daemon/mood process."""
    if not args:
        return False

    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else -1
    if pid is not None and (pid == current_pid or pid == parent_pid):
        return False

    joined = " ".join(args)
    joined_lower = joined.lower()

    # Exclude test runners, linters, or unrelated development / system tools
    exclude_markers = [
        "unittest",
        "pytest",
        "test_",
        "ruff",
        "flake8",
        "black",
        "mypy",
        "git",
        "grep",
        "vim",
        "nano",
        "ulauncher",
    ]
    if any(marker in joined_lower for marker in exclude_markers):
        return False

    # Exclude transient CLI utility commands
    cli_transient_flags = {
        "-h",
        "--help",
        "-l",
        "--list",
        "-P",
        "--show-daemons",
        "--pids",
        "--show-pids",
        "--list-daemons",
        "--daemons",
        "-k",
        "-K",
        "--kill",
        "--kill-daemon",
        "--kill-daemons",
    }
    if any(arg in cli_transient_flags for arg in args):
        return False

    # 1. Direct hume project or module reference
    if "hume" in joined_lower:
        for arg in args:
            base = os.path.basename(arg)
            if base in ("main.py", "hume", "hume.py") or "hume" in arg.lower():
                return True

    # 2. Check process cwd via /proc if available
    if pid is not None and os.path.isdir("/proc"):
        try:
            cwd = os.path.realpath(f"/proc/{pid}/cwd")
            if "hume" in cwd.lower():
                for arg in args:
                    if os.path.basename(arg) in ("main.py", "hume.py"):
                        return True
        except (OSError, IOError, PermissionError):
            pass

    # 3. Direct relative hume.py or main.py invocation
    for arg in args:
        if arg in ("hume.py", "./hume.py", "main.py", "./main.py"):
            return True

    return False


def get_running_daemon_pids() -> list[int]:
    """Find and return all currently running hume daemon PIDs (sorted)."""
    pids: set[int] = set()
    current_pid = os.getpid()
    parent_pid = os.getppid() if hasattr(os, "getppid") else -1

    # 1. Check PID registry directory
    pid_dir = _get_pid_dir()
    if os.path.isdir(pid_dir):
        try:
            for fname in os.listdir(pid_dir):
                if fname.isdigit():
                    pid = int(fname)
                    if pid == current_pid or pid == parent_pid:
                        continue
                    try:
                        os.kill(pid, 0)
                        pids.add(pid)
                    except OSError:
                        # Clean up stale pid file
                        _unregister_daemon_pid(pid)
        except OSError:
            pass

    # 2. Check /proc on Linux
    if os.path.isdir("/proc"):
        try:
            for entry in os.listdir("/proc"):
                if not entry.isdigit():
                    continue
                pid = int(entry)
                if pid == current_pid or pid == parent_pid or pid in pids:
                    continue
                cmdline_file = f"/proc/{pid}/cmdline"
                try:
                    with open(cmdline_file, "rb") as f:
                        raw = f.read()
                    args = [
                        arg.decode("utf-8", errors="replace")
                        for arg in raw.split(b"\x00")
                        if arg
                    ]
                    if _is_hume_daemon_cmdline(args, pid=pid):
                        try:
                            os.kill(pid, 0)
                            pids.add(pid)
                        except OSError:
                            pass
                except (OSError, IOError, PermissionError):
                    continue
        except OSError:
            pass

    # 3. Fallback to `ps` command on systems without /proc (or macOS/BSD)
    if not os.path.isdir("/proc"):
        try:
            proc = subprocess.run(
                ["ps", "-eo", "pid,args"],
                capture_output=True,
                text=True,
                timeout=3.0,
                check=False,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines()[1:]:
                    parts = line.strip().split(None, 1)
                    if len(parts) >= 2 and parts[0].isdigit():
                        pid = int(parts[0])
                        if pid == current_pid or pid == parent_pid or pid in pids:
                            continue
                        args = parts[1].split()
                        if _is_hume_daemon_cmdline(args, pid=pid):
                            try:
                                os.kill(pid, 0)
                                pids.add(pid)
                            except OSError:
                                pass
        except (OSError, subprocess.SubprocessError):
            pass

    # Filter out any non-alive PIDs, current process, or parent process
    alive_pids: list[int] = []
    for pid in sorted(pids):
        if pid == current_pid or pid == parent_pid:
            continue
        try:
            os.kill(pid, 0)
            alive_pids.append(pid)
        except OSError:
            pass

    return sorted(alive_pids)


def show_running_daemon_pids(pids: list[int] | None = None) -> list[int]:
    """Display all currently running daemon PIDs with their command line options, and return the list."""
    if pids is None:
        pids = get_running_daemon_pids()

    if not pids:
        print("No running daemon processes found.")
    else:
        print("Currently running daemon processes:")
        for idx, pid in enumerate(pids, 1):
            print(format_daemon_process_entry(idx, pid))
    return pids


def kill_daemon_by_pid(pid: int, timeout: float = 2.0) -> bool:
    """Terminate a daemon process by PID using SIGTERM with fallback to SIGKILL."""
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _unregister_daemon_pid(pid)
        return True
    except OSError as e:
        logger.error("Failed to send SIGTERM to process %s: %s", pid, e)
        return False

    # Wait briefly for process to exit
    start_time = time.time()
    while time.time() - start_time < timeout:
        try:
            os.kill(pid, 0)
            time.sleep(0.05)
        except ProcessLookupError:
            _unregister_daemon_pid(pid)
            return True
        except OSError:
            break

    # If still alive, force kill with SIGKILL if available
    try:
        if hasattr(signal, "SIGKILL"):
            os.kill(pid, signal.SIGKILL)
            _unregister_daemon_pid(pid)
            return True
    except ProcessLookupError:
        _unregister_daemon_pid(pid)
        return True
    except OSError as e:
        logger.error("Failed to SIGKILL process %s: %s", pid, e)
        return False

    _unregister_daemon_pid(pid)
    return True


def kill_daemon_interactive(
    pids: list[int] | None = None, input_fn: Any = input
) -> bool:
    """List running daemon PIDs and prompt user to enter an index to kill it."""
    if pids is None:
        pids = get_running_daemon_pids()

    if not pids:
        print("No running daemon processes found.")
        return False

    print("Currently running daemon processes:")
    for idx, pid in enumerate(pids, 1):
        print(format_daemon_process_entry(idx, pid))
    print()

    while True:
        try:
            prompt = f"Enter index of daemon to kill (1-{len(pids)}) or 'q' to cancel: "
            user_input = input_fn(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            return False

        if not user_input or user_input.lower() in ("q", "quit", "c", "cancel", "exit"):
            print("Cancelled. No daemon process was killed.")
            return False

        try:
            idx = int(user_input)
            if 1 <= idx <= len(pids):
                target_pid = pids[idx - 1]
                if kill_daemon_by_pid(target_pid):
                    print(f"Killed daemon process with PID {target_pid}.")
                    return True
                else:
                    print(f"Failed to kill daemon process with PID {target_pid}.")
                    return False
            else:
                print(
                    f"Invalid index: {idx}. Please enter a number between 1 and {len(pids)} (or 'q' to cancel)."
                )
        except ValueError:
            print(
                f"Invalid input: '{user_input}'. Please enter a number between 1 and {len(pids)} (or 'q' to cancel)."
            )


def fork_daemon_process(argv: list[str] | None = None) -> int:
    """Fork the current process into background, exit the parent, and display child PID/task ID.

    Returns the PID of the running child process.
    """
    if hasattr(os, "fork"):
        pid = os.fork()
        if pid > 0:
            # Parent process: exit immediately so the calling shell returns
            sys.exit(0)

    child_pid = os.getpid()
    if argv is None:
        argv = sys.argv[1:] if isinstance(sys.argv, list) else []
    _register_daemon_pid(child_pid, args=argv)
    print(f"Daemon process started with PID: {child_pid}", flush=True)
    logger.info("Daemon process running with PID: %s", child_pid)
    return child_pid


def generate_wrapper_script(script_path: str | None = None) -> str:
    """Generate the contents of the wrapper shell script for running hume.py.

    The wrapper script runs the Python script and forwards all command-line
    arguments ("$@"). It prefers uv if available, then the project's virtualenv,
    then python3 / python.
    """
    if script_path is None:
        script_path = os.path.abspath(os.path.realpath(__file__))
    else:
        script_path = os.path.abspath(os.path.realpath(script_path))

    project_dir = os.path.dirname(script_path)

    return f"""#!/usr/bin/env bash
# Wrapper script for hume (Philips Hue CLI utility)
# Auto-generated by: hume --install

SCRIPT_PATH="{script_path}"
PROJECT_DIR="{project_dir}"

if command -v uv >/dev/null 2>&1; then
    exec uv run --project "$PROJECT_DIR" python "$SCRIPT_PATH" "$@"
elif [ -x "$PROJECT_DIR/.venv/bin/python" ]; then
    exec "$PROJECT_DIR/.venv/bin/python" "$SCRIPT_PATH" "$@"
elif command -v python3 >/dev/null 2>&1; then
    exec python3 "$SCRIPT_PATH" "$@"
else
    exec python "$SCRIPT_PATH" "$@"
fi
"""


def find_install_dir(path_env: str | None = None) -> str | None:
    """Find a suitable, writable directory in the user's $PATH to install the hume script.

    Priority order:
    1. Standard user bin directories in $PATH (~/.local/bin, ~/bin) that exist and are writable (or parent writable).
    2. Other persistent user-home directories in $PATH (excluding project virtualenvs) that are writable.
    3. Other system directories in $PATH (excluding project virtualenvs) that are writable.
    4. Any other writable directory in $PATH (including active virtual environments).
    """
    path_str = os.getenv("PATH", "") if path_env is None else path_env
    if not path_str:
        return None

    raw_entries = path_str.split(os.pathsep)
    home_dir = os.path.abspath(os.path.expanduser("~"))
    std_user_bins = {
        os.path.abspath(os.path.join(home_dir, ".local", "bin")),
        os.path.abspath(os.path.join(home_dir, "bin")),
    }

    # Normalize entries and remove duplicates while preserving order
    candidates: list[str] = []
    seen: set[str] = set()
    for entry in raw_entries:
        entry = entry.strip()
        if not entry:
            continue
        expanded = os.path.abspath(os.path.expanduser(entry))
        if expanded not in seen:
            seen.add(expanded)
            candidates.append(expanded)

    def _is_writable(d: str) -> bool:
        if os.path.isdir(d):
            return os.access(d, os.W_OK)
        if not os.path.exists(d):
            parent = os.path.dirname(d)
            return os.path.isdir(parent) and os.access(parent, os.W_OK)
        return False

    def _is_venv(d: str) -> bool:
        parts = d.split(os.sep)
        return any(p in (".venv", "venv", "__pypackages__") for p in parts)

    # 1. Standard user bin directories (~/.local/bin, ~/bin) in PATH
    for d in candidates:
        if d in std_user_bins and _is_writable(d):
            return d

    # 2. Other user-home directories in PATH (excluding venvs)
    for d in candidates:
        if d.startswith(home_dir) and not _is_venv(d) and _is_writable(d):
            return d

    # 3. System directories in PATH (excluding venvs)
    for d in candidates:
        if not _is_venv(d) and _is_writable(d):
            return d

    # 4. Any remaining writable directory in PATH
    for d in candidates:
        if _is_writable(d):
            return d

    return None


def install_hume_script(
    target_dir: str | None = None,
    script_path: str | None = None,
    path_env: str | None = None,
) -> tuple[bool, str]:
    """Install the hume executable shell script into a directory in $PATH.

    Returns (success, destination_path).
    """
    if target_dir is None:
        target_dir = find_install_dir(path_env=path_env)

    if not target_dir:
        logger.error(
            "Could not find a writable directory in $PATH. "
            "Please ensure a directory such as ~/.local/bin or ~/bin is in your PATH and writable."
        )
        return False, ""

    try:
        os.makedirs(target_dir, exist_ok=True)
        dest_path = os.path.join(target_dir, "hume")
        content = generate_wrapper_script(script_path=script_path)

        with open(dest_path, "w", encoding="utf-8") as f:
            f.write(content)

        # Set executable permissions (rwxr-xr-x)
        os.chmod(dest_path, 0o755)
        logger.info("Successfully installed hume shell script to %s", dest_path)
        return True, dest_path
    except OSError as e:
        logger.error("Failed to install hume shell script to %s: %s", target_dir, e)
        return False, ""


def load_config() -> Dict[str, Any]:
    """Load configuration from environment with defaults.

    Returns a dict with keys: user_id (str|None), bridge_ip (str), log_level (str), timeout (float), daemon (bool).
    Note: user_id may be None; main() validates and handles errors with messaging.
    """
    user_id = os.getenv("HUE_USER_ID")
    bridge_ip = os.getenv("HUE_BRIDGE_IP", "192.168.2.19")
    log_level = os.getenv("LOG_LEVEL", "INFO")
    timeout_raw = os.getenv("REQUEST_TIMEOUT", "5.0")
    daemon = is_daemon_mode()
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
        "daemon": daemon,
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


def format_table(headers: list[str], rows: list[list[Any]], title: str | None = None) -> str:
    """Format tabular data into an ASCII grid/table string."""
    max_row_len = max((len(r) for r in rows), default=0) if rows else 0
    num_cols = max(len(headers), max_row_len)
    if num_cols == 0:
        return f"=== {title} ===\n(No data)" if title else ""

    norm_headers = [str(h) for h in headers] if headers else []
    while len(norm_headers) < num_cols:
        norm_headers.append("")

    norm_rows: list[list[str]] = []
    for r in rows:
        row_strs = [str(cell) if cell is not None else "" for cell in r]
        while len(row_strs) < num_cols:
            row_strs.append("")
        norm_rows.append(row_strs)

    col_widths = [len(h) for h in norm_headers]
    for r in norm_rows:
        for i, cell in enumerate(r):
            col_widths[i] = max(col_widths[i], len(cell))

    sep = "+" + "+".join("-" * (w + 2) for w in col_widths) + "+"
    lines: list[str] = []

    if title:
        lines.append(f"=== {title} ===")

    lines.append(sep)
    if headers:
        header_line = "| " + " | ".join(h.ljust(col_widths[i]) for i, h in enumerate(norm_headers)) + " |"
        lines.append(header_line)
        lines.append(sep)

    for r in norm_rows:
        row_line = "| " + " | ".join(cell.ljust(col_widths[i]) for i, cell in enumerate(r)) + " |"
        lines.append(row_line)

    lines.append(sep)
    return "\n".join(lines)


def _format_bridge_config_table(config: dict[str, Any]) -> str:
    field_labels = [
        ("name", "Bridge Name"),
        ("modelid", "Model ID"),
        ("bridgeid", "Bridge ID"),
        ("ipaddress", "IP Address"),
        ("mac", "MAC Address"),
        ("apiversion", "API Version"),
        ("swversion", "Software Version"),
        ("zigbeechannel", "Zigbee Channel"),
        ("timezone", "Timezone"),
        ("localtime", "Local Time"),
        ("gateway", "Gateway IP"),
        ("netmask", "Netmask"),
        ("dhcp", "DHCP"),
        ("linkbutton", "Link Button"),
    ]
    rows: list[list[str]] = []
    seen = set()
    for key, label in field_labels:
        if key in config:
            val = config[key]
            rows.append([label, str(val)])
            seen.add(key)

    for key, val in config.items():
        if key not in seen and not isinstance(val, (dict, list)):
            rows.append([str(key), str(val)])

    if not rows:
        return ""
    return format_table(["Property", "Value"], rows, title="Bridge Configuration")


def _format_lights_table(lights: dict[str, Any]) -> str:
    headers = ["ID", "Name", "Type", "State", "Brightness", "Color Info", "Reachable", "Model ID"]
    rows: list[list[str]] = []

    def sort_key(k: str) -> tuple[int, str | int]:
        return (0, int(k)) if k.isdigit() else (1, k)

    for lid in sorted(lights.keys(), key=sort_key):
        info = lights[lid]
        if not isinstance(info, dict):
            rows.append([str(lid), str(info), "-", "-", "-", "-", "-", "-"])
            continue

        name = str(info.get("name", "-"))
        ltype = str(info.get("type", "-"))
        modelid = str(info.get("modelid", "-"))
        state = info.get("state", {}) if isinstance(info.get("state"), dict) else {}

        on_val = state.get("on")
        state_str = "ON" if on_val is True else ("OFF" if on_val is False else "-")

        bri = state.get("bri")
        if bri is not None and isinstance(bri, (int, float)):
            pct = round((bri / 254.0) * 100)
            bri_str = f"{int(bri)} ({pct}%)"
        else:
            bri_str = "-"

        colormode = state.get("colormode")
        if colormode == "hs" or ("hue" in state and "sat" in state):
            h = state.get("hue")
            s = state.get("sat")
            color_str = f"hue:{h} sat:{s}"
        elif colormode == "ct" or "ct" in state:
            ct = state.get("ct")
            color_str = f"ct:{ct}"
        elif colormode == "xy" or "xy" in state:
            xy = state.get("xy")
            color_str = f"xy:{xy}"
        else:
            color_str = "-"

        reachable_val = state.get("reachable")
        reach_str = "Yes" if reachable_val is True else ("No" if reachable_val is False else "-")

        rows.append([str(lid), name, ltype, state_str, bri_str, color_str, reach_str, modelid])

    return format_table(headers, rows, title="Discovered Lights")


def _format_groups_table(groups: dict[str, Any]) -> str:
    headers = ["ID", "Group Name", "Type", "Lights", "State"]
    rows: list[list[str]] = []

    def sort_key(k: str) -> tuple[int, str | int]:
        return (0, int(k)) if k.isdigit() else (1, k)

    for gid in sorted(groups.keys(), key=sort_key):
        info = groups[gid]
        if not isinstance(info, dict):
            rows.append([str(gid), str(info), "-", "-", "-"])
            continue

        name = str(info.get("name", "-"))
        gtype = str(info.get("type", "-"))
        lights_list = info.get("lights", [])
        lights_str = ", ".join(str(x) for x in lights_list) if isinstance(lights_list, list) and lights_list else "-"

        state = info.get("state", {}) if isinstance(info.get("state"), dict) else {}
        action = info.get("action", {}) if isinstance(info.get("action"), dict) else {}

        if state.get("all_on") is True:
            state_str = "ALL ON"
        elif state.get("any_on") is True:
            state_str = "ANY ON"
        elif action.get("on") is True:
            state_str = "ON"
        elif action.get("on") is False or state.get("all_on") is False:
            state_str = "ALL OFF"
        else:
            state_str = "-"

        rows.append([str(gid), name, gtype, lights_str, state_str])

    return format_table(headers, rows, title="Groups & Rooms")


def _format_scenes_table(scenes: dict[str, Any]) -> str:
    headers = ["ID", "Scene Name", "Type", "Group", "Lights"]
    rows: list[list[str]] = []

    for sid in sorted(scenes.keys()):
        info = scenes[sid]
        if not isinstance(info, dict):
            rows.append([str(sid), str(info), "-", "-", "-"])
            continue

        name = str(info.get("name", "-"))
        stype = str(info.get("type", "-"))
        group = str(info.get("group", "-"))
        lights_list = info.get("lights", [])
        lights_str = ", ".join(str(x) for x in lights_list) if isinstance(lights_list, list) and lights_list else "-"

        rows.append([str(sid), name, stype, group, lights_str])

    return format_table(headers, rows, title="Scenes")


def _format_sensors_table(sensors: dict[str, Any]) -> str:
    headers = ["ID", "Sensor Name", "Type", "Model ID"]
    rows: list[list[str]] = []

    def sort_key(k: str) -> tuple[int, str | int]:
        return (0, int(k)) if k.isdigit() else (1, k)

    for sid in sorted(sensors.keys(), key=sort_key):
        info = sensors[sid]
        if not isinstance(info, dict):
            rows.append([str(sid), str(info), "-", "-"])
            continue

        name = str(info.get("name", "-"))
        stype = str(info.get("type", "-"))
        modelid = str(info.get("modelid", "-"))
        rows.append([str(sid), name, stype, modelid])

    return format_table(headers, rows, title="Sensors")


def format_bridge_state(data: Any) -> str:
    """Format the Hue bridge configuration and devices into a readable grid/table layout."""
    if not data:
        return format_table(["Property", "Value"], [["Status", "No configuration data returned."]], title="Bridge State")

    if not isinstance(data, dict):
        if isinstance(data, list):
            rows = [[str(i), json.dumps(item) if isinstance(item, (dict, list)) else str(item)] for i, item in enumerate(data)]
            return format_table(["Index", "Value"], rows, title="Bridge State")
        return format_table(["Property", "Value"], [["Value", str(data)]], title="Bridge State")

    sections: list[str] = []

    if "config" in data and isinstance(data["config"], dict):
        cfg_tbl = _format_bridge_config_table(data["config"])
        if cfg_tbl:
            sections.append(cfg_tbl)

    if "lights" in data and isinstance(data["lights"], dict):
        lights_tbl = _format_lights_table(data["lights"])
        if lights_tbl:
            sections.append(lights_tbl)

    if "groups" in data and isinstance(data["groups"], dict) and data["groups"]:
        groups_tbl = _format_groups_table(data["groups"])
        if groups_tbl:
            sections.append(groups_tbl)

    if "scenes" in data and isinstance(data["scenes"], dict) and data["scenes"]:
        scenes_tbl = _format_scenes_table(data["scenes"])
        if scenes_tbl:
            sections.append(scenes_tbl)

    if "sensors" in data and isinstance(data["sensors"], dict) and data["sensors"]:
        sensors_tbl = _format_sensors_table(data["sensors"])
        if sensors_tbl:
            sections.append(sensors_tbl)

    if not sections:
        is_lights_like = all(isinstance(v, dict) and ("name" in v or "state" in v) for v in data.values()) if data else False
        if is_lights_like:
            return _format_lights_table(data)

        rows = []
        for k, v in data.items():
            val_str = json.dumps(v, indent=2) if isinstance(v, (dict, list)) else str(v)
            rows.append([str(k), val_str])
        return format_table(["Property", "Value"], rows, title="Bridge Configuration")

    return "\n\n".join(sections)


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
    if value is not None and value < 0.5:
        value = 0.5
    return float(value) if value is not None else float(default)


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
    user_id = str(cfg.get("user_id") or "")
    bridge_ip = str(cfg.get("bridge_ip") or "192.168.2.19")
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

            # 5. Convert duration to deciseconds (100ms units) for native bridge transition
            transition_ds = int(round(t_seconds * 10))

            # 6. Issue ONE single command to the bridge for hardware-accelerated transition
            try:
                set_light_state(
                    base_url,
                    light_id,
                    on=True,
                    bri=tgt_bri,
                    hue=tgt_hue,
                    sat=tgt_sat,
                    transitiontime=transition_ds,
                    timeout=timeout,
                )
            except requests.exceptions.RequestException as e:
                logger.warning("Transient error setting light state: %s", e)

            # 7. Sleep for the transition duration while remaining interruptible
            if stop_event is not None:
                if stop_event.wait(timeout=t_seconds):
                    break
            else:
                time.sleep(t_seconds)
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


def _parse_csv_names(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [p.strip() for p in str(value).split(",")]
    return [p for p in parts if p]


def _unique_preserve_order(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for it in items:
        if it not in seen:
            seen.add(it)
            out.append(it)
    return out


def _get_cli_bulb_names(argv: list[str] | None = None) -> list[str] | None:
    """Parse bulb names from CLI.

    Supports:
    --bulbs=CSV
    --bulbs CSV
    -b CSV
    Returns None if not provided or empty.
    """
    if argv is None:
        argv = sys.argv[1:] if isinstance(sys.argv, list) else []

    # --bulbs=VALUE
    for arg in argv:
        if isinstance(arg, str) and arg.startswith("--bulbs="):
            names = _parse_csv_names(arg.split("=", 1)[1])
            return names or None

    # --bulbs VALUE and -b VALUE
    for i, arg in enumerate(argv):
        if arg == "--bulbs" and i + 1 < len(argv):
            names = _parse_csv_names(argv[i + 1])
            return names or None
        if arg == "-b" and i + 1 < len(argv):
            names = _parse_csv_names(argv[i + 1])
            return names or None

    return None


def _is_all_bulbs_flag(argv: list[str] | None = None) -> bool:
    """Check if --all or -a flag is passed on CLI."""
    if argv is None:
        argv = sys.argv[1:] if isinstance(sys.argv, list) else []
    return any(arg in ("-a", "--all") for arg in argv)


def _get_env_bulb_names() -> list[str] | None:
    env_val = os.getenv("HUE_MOOD_BULBS")
    names = _parse_csv_names(env_val)
    return names or None


def get_mood_bulb_names(
    base_url: str,
    timeout: float = 5.0,
    argv: list[str] | None = None,
    use_all: bool | None = None,
) -> list[str]:
    """Determine which bulb names to run mood on.

    Precedence:
    1) CLI (--bulbs/-b) if provided
    2) CLI (--all/-a) or use_all=True: all bulbs of type "Extended color light" discovered from bridge
    3) Environment (HUE_MOOD_BULBS)
    4) Default: None (logs error; bulbs must be specified or --all/-a used)
    """
    # 1) CLI specific bulbs
    cli = _get_cli_bulb_names(argv)
    if cli:
        names = _unique_preserve_order([n for n in cli if n])
        logger.debug("Using bulb names from CLI: %s", ", ".join(names))
        return names

    # 2) CLI --all / -a or use_all parameter
    is_all = use_all if use_all is not None else _is_all_bulbs_flag(argv)
    if is_all:
        try:
            lights = get_lights(base_url, timeout=timeout) or {}
        except requests.exceptions.RequestException as e:
            logger.error("Failed to list bulbs from Hue Bridge: %s", e)
            return []

        # Sort by numeric id for determinism
        def _id_key(item: tuple[str, Any]) -> int:
            try:
                return int(item[0])
            except Exception:
                return 0

        names: list[str] = []
        for lid, info in sorted(lights.items(), key=_id_key):
            try:
                name = str(info.get("name", "")).strip()
            except Exception:
                name = ""
            # Filter by type: only Extended color light
            try:
                ltype = str(info.get("type", "")).strip().lower()
            except Exception:
                ltype = ""
            if name and ltype == "extended color light":
                names.append(name)

        names = _unique_preserve_order(names)
        logger.debug(
            "Discovered all bulbs for mood (Extended color light only): %s",
            ", ".join(names) if names else "<none>",
        )
        return names

    # 3) ENV
    env_names = _get_env_bulb_names()
    if env_names:
        names = _unique_preserve_order([n for n in env_names if n])
        logger.debug("Using bulb names from HUE_MOOD_BULBS: %s", ", ".join(names))
        return names

    # 4) If neither CLI bulbs, --all, nor env bulbs are provided, treat as error
    logger.error(
        "No bulbs specified. Please specify bulbs with --bulbs / -b, HUE_MOOD_BULBS, or use --all / -a to target all bulbs."
    )
    return []


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


def _wait_for_signal_or_stop_event(stop_event: threading.Event) -> None:
    """Block until stop_event is set or SIGTERM/SIGINT is received."""
    orig_handlers: dict[int, Any] = {}
    signals_to_catch = [signal.SIGINT, signal.SIGTERM]
    if hasattr(signal, "SIGHUP"):
        signals_to_catch.append(signal.SIGHUP)

    def _sig_handler(signum: int, frame: Any) -> None:
        logger.info("Received signal %s; shutting down...", signum)
        stop_event.set()

    is_main_thread = threading.current_thread() is threading.main_thread()
    if is_main_thread:
        for sig in signals_to_catch:
            try:
                orig_handlers[sig] = signal.signal(sig, _sig_handler)
            except (ValueError, OSError, AttributeError):
                pass

    try:
        while not stop_event.is_set():
            stop_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        stop_event.set()
    finally:
        if is_main_thread:
            for sig, handler in orig_handlers.items():
                try:
                    signal.signal(sig, handler)
                except (ValueError, OSError, AttributeError):
                    pass


def run_mood_application(
    daemon: bool | None = None,
    stop_event: threading.Event | None = None,
    argv: list[str] | None = None,
    use_all: bool | None = None,
) -> None:
    """Start mood threads for selected bulbs and wait for stop.

    In interactive mode (default), waits for ESC key or Ctrl-C.
    In daemon mode (daemon=True or via CLI/env), runs non-interactively and waits for SIGTERM/SIGINT.

    Bulbs must be specified via CLI (--bulbs/-b), environment (HUE_MOOD_BULBS),
    or targeted in full with --all / -a (or use_all=True).
    """
    if daemon is None:
        daemon = is_daemon_mode(argv)

    cfg = load_config()
    user_id = str(cfg.get("user_id") or "")
    bridge_ip = str(cfg.get("bridge_ip") or "192.168.2.19")
    timeout = float(cfg.get("timeout", 5.0))

    if not user_id:
        logger.error("HUE_USER_ID is not set; cannot start mood application.")
        return

    base_url = build_base_url(user_id, bridge_ip)

    bulbs = get_mood_bulb_names(base_url, timeout=timeout, argv=argv, use_all=use_all)
    if not bulbs:
        logger.warning("No bulbs available or specified; nothing to do.")
        return

    if daemon:
        fork_daemon_process(argv=argv)

    if stop_event is None:
        stop_event = threading.Event()

    threads = []
    for name in bulbs:
        t = start_mood_thread(name, stop_event)
        threads.append(t)
    logger.info("Mood threads started for bulbs: %s", ", ".join(bulbs))

    try:
        if daemon:
            logger.info("Running in daemon mode. Waiting for termination signal (SIGTERM/SIGINT) to stop...")
            _wait_for_signal_or_stop_event(stop_event)
        else:
            logger.info("Press ESC (or Ctrl-C) to stop and restore bulbs...")
            _wait_for_escape_or_sigint()
    finally:
        logger.info("Stopping mood threads and restoring bulbs...")
        stop_event.set()
        # Join threads briefly; they restore on exit
        for t in threads:
            t.join(timeout=10.0)
        logger.info("All mood threads stopped.")
        if daemon:
            _unregister_daemon_pid(os.getpid())


def main(show_config: bool = False) -> int:
    cfg = load_config()

    # Configure logging early
    setup_logging(cfg.get("log_level"))

    user_id = str(cfg.get("user_id") or "")
    bridge_ip = str(cfg.get("bridge_ip") or "192.168.2.19")
    timeout = float(cfg.get("timeout", 5.0))

    if not user_id:
        logger.error(
            "HUE_USER_ID is not set. Please export HUE_USER_ID before running. See README.md."
        )
        return 1

    redacted_user = _redact_user_id(user_id)
    logger.debug("Effective configuration: bridge_ip=%s, user_id=%s, timeout=%s", bridge_ip, redacted_user, timeout)

    base_url = build_base_url(user_id, bridge_ip)
    if show_config:
        logger.info("Fetching Hue bridge state from http://%s/... (base path)", bridge_ip)
    else:
        logger.debug("Checking Hue bridge connection at http://%s/...", bridge_ip)

    try:
        data = fetch_bridge_state(base_url, timeout=timeout)
        if show_config:
            formatted = format_bridge_state(data)
            logger.info("\n%s", formatted)
        return 0
    except requests.exceptions.RequestException as e:
        logger.error("Network error talking to Hue Bridge at %s: %s", bridge_ip, e)
        return 2
    except ValueError as e:
        logger.error("Failed to parse Hue Bridge response: %s", e)
        return 3


def cli_entrypoint(argv: list[str] | None = None) -> int:
    """Main CLI entrypoint for parsing flags, running query commands, or starting mood."""
    if argv is None:
        argv = sys.argv[1:] if isinstance(sys.argv, list) else []

    # Help: show usage and exit without performing any network I/O or starting mood.
    if any(arg in ("-h", "--help") for arg in argv):
        print(
            """Usage: python hume.py [options]

Options:
  -h, --help                  Show this help message and exit
  -i, --install               Install hume shell script to a directory in $PATH and exit
  -l, --list                  Fetch and display Hue bridge configuration, then exit
  -a, --all                   Use all discovered color bulbs for mood lighting
  -d, -p, --daemon            Run in non-interactive daemon mode (wait for SIGTERM/SIGINT)
  -P, --show-daemons, --pids  Display all currently running daemon PIDs and exit
  -k, --kill, --kill-daemon   List running daemon PIDs and prompt to kill one by index
  -M SEC, --mood-max-seconds SEC
                              Maximum transition duration for mood lighting
                              (default via HUE_MOOD_MAX_SECONDS)
  -b NAMES, --bulbs NAMES     Comma-separated bulb names for mood lighting
                              (default via HUE_MOOD_BULBS)

Environment:
  HUE_USER_ID                 Required at runtime
  HUE_BRIDGE_IP               Hue bridge IP (default 192.168.2.19)
  LOG_LEVEL                   Logging level (default INFO)
  REQUEST_TIMEOUT             Network timeout seconds (default 5.0)
  HUE_MOOD_MAX_SECONDS        Max transition seconds for mood lighting (default 30.0)
  HUE_MOOD_BULBS              Bulb names, comma-separated
  HUE_DAEMON                  Enable daemon mode if set to 1/true
"""
        )
        return 0

    if any(arg in ("-i", "--install") for arg in argv):
        cfg = load_config()
        setup_logging(cfg.get("log_level"))
        success, dest = install_hume_script()
        if success:
            print(f"hume installed successfully to {dest}")
            return 0
        return 1

    if any(
        arg in ("-P", "--show-daemons", "--pids", "--show-pids", "--list-daemons", "--daemons")
        for arg in argv
    ):
        show_running_daemon_pids()
        return 0

    if any(
        arg in ("-k", "-K", "--kill", "--kill-daemon", "--kill-daemons")
        for arg in argv
    ):
        kill_daemon_interactive()
        return 0

    # Detect list-only mode: when -l/--list is provided, we only display the
    # Hue bridge configuration and exit without starting the mood application.
    list_only = any(arg in ("-l", "--list") for arg in argv)

    if not list_only:
        cli_bulbs = _get_cli_bulb_names(argv)
        all_bulbs = _is_all_bulbs_flag(argv)
        env_bulbs = _get_env_bulb_names()
        if not cli_bulbs and not all_bulbs and not env_bulbs:
            cfg = load_config()
            setup_logging(cfg.get("log_level"))
            logger.error(
                "No bulbs specified. Please specify bulbs with --bulbs / -b or use --all / -a to target all bulbs."
            )
            return 1

    rc = main(show_config=list_only)
    if rc == 0 and not list_only:
        # Start mood application (interactive with ESC/Ctrl-C or daemon mode with signals)
        daemon_mode = is_daemon_mode(argv)
        run_mood_application(daemon=daemon_mode, argv=argv)
    return rc


if __name__ == "__main__":
    sys.exit(cli_entrypoint())
