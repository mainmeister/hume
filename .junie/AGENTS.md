# Agent & Developer Guidelines: `hume`

`hume` is a minimal, modular Python utility for interacting with a Philips Hue bridge and running dynamic real-time mood lighting loops across Hue color bulbs.

---

## 1. Build & Configuration Instructions

### Environment & Python Runtime
- **Python**: Requires Python `>=3.12` (enforced via `pyproject.toml`).
- **Package & Environment Manager**: `uv` with `uv.lock`.

### Setup & Installation
1. **Install `uv`** (if not installed):
   - Linux/macOS: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Windows (PowerShell): `iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex`
2. **Synchronize Dependencies**:
   ```bash
   uv sync
   ```
3. **Add/Update Dependencies**:
   ```bash
   uv add <package-name>
   uv lock
   ```

### Configuration & Environment Variables
Configuration is loaded via `main.load_config()` with fallback defaults:

| Variable | Required | Default | Description |
|---|---|---|---|
| `HUE_USER_ID` | Yes (runtime) | `None` | Registered Hue bridge API username/token. Must not be committed. |
| `HUE_BRIDGE_IP` | No | `192.168.1.2` | IP address of the Philips Hue bridge. |
| `LOG_LEVEL` | No | `INFO` | Logging level (`DEBUG`, `INFO`, `WARNING`, `ERROR`). |
| `REQUEST_TIMEOUT` | No | `5.0` | Timeout in seconds for HTTP requests to prevent network hangs. |
| `HUE_MOOD_MAX_SECONDS` | No | `30.0` | Upper bound for random transition duration in mood loops. |
| `HUE_MOOD_BULBS` | No | Discovered bulbs | Comma-separated list of bulb names to target for mood lighting. |
| `INTEGRATION` | No | `0` | Set to `1` to enable real-hardware integration tests. |

### Running the Application
- **Fetch bridge state & start mood lighting**:
  ```bash
  export HUE_USER_ID="<your-user-id>"
  uv run python main.py
  ```
- **List bridge configuration only (no mood lighting)**:
  ```bash
  uv run python main.py --list
  ```
- **Specify bulbs and transition times via CLI flags**:
  ```bash
  uv run python main.py --bulbs "Living Room,Bedroom" --mood-max-seconds 15.0
  ```
  *(Precedence: CLI flags > Environment variables > Bridge defaults)*

---

## 2. Testing Information

### Test Framework & Discovery
- Built with Python's standard `unittest` library (no external test runner dependencies needed).
- Test directory: `tests/`
- Test files must follow naming pattern: `test_*.py`

### Executing Tests
- **Run all unit tests**:
  ```bash
  uv run python -m unittest discover -s tests -v
  ```
- **Run a specific test module**:
  ```bash
  uv run python -m unittest tests.test_config -v
  ```
- **Run a specific test case / method**:
  ```bash
  uv run python -m unittest tests.test_config.TestConfig.test_defaults_when_env_missing -v
  ```
- **Run integration tests (requires live Hue bridge and network access)**:
  ```bash
  INTEGRATION=1 HUE_USER_ID="<your-user-id>" uv run python -m unittest discover -s tests -v
  ```

### Guidelines for Adding New Tests
1. **Network & Side-Effect Isolation**:
   - Unit tests must **never** perform live network calls or rely on a reachable Hue Bridge.
   - Mock HTTP requests using `unittest.mock.patch('requests.get')` or `unittest.mock.patch('requests.put')`.
2. **Environment Isolation**:
   - Isolate environment variables using `unittest.mock.patch.dict(os.environ, {...}, clear=True)`.
3. **Integration Test Guarding**:
   - Always decorate integration tests with `@unittest.skipUnless(os.getenv("INTEGRATION") == "1", "requires integration env")`.

### Working Test Example
The following pattern demonstrates how to write and execute a new unit test for endpoints and URL composition:

```python
import unittest
from unittest.mock import patch, MagicMock
import main


class TestExampleEndpoint(unittest.TestCase):
    def test_build_base_url_custom(self) -> None:
        url = main.build_base_url("sample_user", "192.168.1.50")
        self.assertEqual(url, "http://192.168.1.50/api/sample_user/")

    def test_get_lights_mocked(self) -> None:
        with patch("requests.get") as mock_get:
            mock_resp = MagicMock()
            mock_resp.json.return_value = {"1": {"name": "Living Room"}}
            mock_get.return_value = mock_resp

            lights = main.get_lights("http://192.168.1.50/api/sample_user/")
            self.assertEqual(lights, {"1": {"name": "Living Room"}})
            mock_get.assert_called_once_with(
                "http://192.168.1.50/api/sample_user/lights", timeout=5.0
            )


if __name__ == "__main__":
    unittest.main()
```

---

## 3. Additional Development & Debugging Information

### Architecture & Design Patterns
- **Import Safety**: Modules must avoid network operations and side effects during import time. All executions are encapsulated in functions (`load_config`, `fetch_bridge_state`, `main`) and guarded with `if __name__ == "__main__": sys.exit(main())`.
- **API Function Decomposition**:
  - `load_config() -> Dict[str, Any]`: Loads and validates settings from environment with fallbacks.
  - `build_base_url(user_id, bridge_ip) -> str`: Builds `http://{bridge_ip}/api/{user_id}/`.
  - `_endpoint(base_url, path) -> str`: Normalizes endpoint URLs without trailing/leading slash conflicts.
  - `fetch_bridge_state(base_url, timeout)`: Fetches full bridge JSON state.
  - `get_lights`, `get_light_state`, `set_light_state`: Interacts with individual Hue light endpoints.
  - `resolve_light_id_by_name`: Case-insensitive resolution of bulb names to IDs.
  - `get_all_bulbs`, `filter_extended_color_lights`: Discovery and filtering of color-capable lights.
  - `mood`, `start_mood_thread`: Manages multithreaded dynamic color/brightness transitions.
- **Concurrency & Graceful Teardown**:
  - Mood loops execute within daemon threads.
  - Threads accept a `threading.Event` as `stop_event` for cooperative shutdown.
  - When stopping (via ESC key or `stop_event.set()`), `mood()` captures initial light states and restores them on exit.

### Code Style & Best Practices
- **Type Annotations**: Use Python type hints on all public function signatures (`from __future__ import annotations`, `typing.Dict`, `typing.Optional`, `typing.Any`, etc.).
- **Logging**: Use standard Python `logging.getLogger(__name__)`. Do not use raw `print` calls for operational logging or errors; respect `LOG_LEVEL`.
- **Error Handling**:
  - Catch `requests.exceptions.RequestException` and handle network disconnects or timeouts gracefully.
  - Handle JSON parsing errors and raise descriptive exceptions (`ValueError("Invalid JSON response from Hue Bridge")`).
- **Timeouts**: Every network request must explicitly pass `timeout` to avoid hangs.
