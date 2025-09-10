Project: hume — Development Guidelines

Audience: Advanced developers working on a minimal Philips Hue control utility.

1. Build and Configuration
- Python runtime: 3.12+ (enforced by pyproject)
- Dependency manager: uv (uv.lock present)
  - Install uv (one-liner):
    - Linux/macOS: curl -LsSf https://astral.sh/uv/install.sh | sh
    - Windows (PowerShell): iwr https://astral.sh/uv/install.ps1 -UseBasicParsing | iex
  - Create/activate a virtualenv (optional, uv can manage it implicitly):
    - uv venv
    - source .venv/bin/activate (Linux/macOS) or .venv\Scripts\activate (Windows)
  - Install project with locked dependencies:
    - uv sync
- Direct run without global install:
  - uv run python main.py
- Required environment
  - HUE_USER_ID: Required at runtime. If missing, importing main.py raises KeyError by design (see tests below).
  - BRIDGE_IP: Currently hard-coded in main.py as 192.168.1.2. You likely want to make this configurable in future work (see Dev Notes).
- Network access: main.py performs an HTTP GET to http://{BRIDGE_IP}/api/{HUE_USER_ID}/ at import-time. Running it without a reachable Hue Bridge will fail or hang. Use a network-isolated approach for tests (see Testing).

2. Testing
- Framework: Python’s built-in unittest (no extra deps).
- Running all tests:
  - uv run python -m unittest discover -s tests -v
- Adding new tests:
  - Place test modules under tests/ and name them test_*.py.
  - Prefer small, isolated units that do not require network or hardware. If you must interact with the Hue Bridge, guard such tests behind environment flags and skip by default:
    - Use unittest.skipUnless(os.getenv("INTEGRATION") == "1", "requires integration env")
- Mocking external calls:
  - main.py issues requests.get at import-time. For testability, prefer refactoring to move side effects into a main() entrypoint. Until then, avoid importing main in tests that run without HUE_USER_ID or network; or patch requests.get before import using import hooks if necessary.
- Example test that was validated locally (2 tests passed):
  - tests/test_basic.py (temporary during authoring)
    - Verifies that importing main without HUE_USER_ID raises KeyError.
    - Verifies URL composition logic without hitting the network.
- Coverage: Not configured. If you add coverage, prefer uv run coverage run -m pytest or coverage with unittest, but keep it optional.

3. Development Notes / Conventions
- Code structure: Currently a single script main.py. For maintainability:
  - Move network I/O and Hue logic into functions (e.g., build_base_url(user_id, bridge_ip), fetch_bridge_state(base_url)).
  - Gate runtime behavior under if __name__ == "__main__": to avoid side effects on import; this will simplify testing.
- Configuration:
  - Avoid hard-coded BRIDGE_IP; allow override via env var (e.g., HUE_BRIDGE_IP) or a small config file.
  - Always set timeouts on requests (e.g., requests.get(url, timeout=5)) to prevent hangs when the bridge is unreachable.
- Logging: Replace print with logging module; respect LOG_LEVEL env variable. Example:
  - import logging; logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))
- Error handling:
  - Gracefully handle requests.exceptions.RequestException and JSON decoding errors; provide actionable diagnostics.
- Dependency hygiene:
  - All runtime deps are declared in pyproject.toml and locked in uv.lock. Commit updates to uv.lock when changing dependencies: uv add <pkg> && uv lock (or uv sync which updates the lock as needed).
- Running the script:
  - Export HUE_USER_ID in your shell and ensure the bridge IP is correct/accessible, then:
    - uv run python main.py
- IDEs: The repo contains IntelliJ/PyCharm .idea configs; these are optional. Ensure your interpreter matches Python 3.12 and uses the uv-managed venv.

4. Reproducible Example (validated)
- Commands executed successfully during preparation:
  - uv sync
  - uv run python -m unittest discover -s tests -v
  - Results: 2 tests executed, 2 passed.
- Note: The tests directory used for demonstration was temporary and may not be present in the repo after cleanup. Use the snippets above to recreate.

5. Future Enhancements
- Introduce a CLI with argparse/typer for operations (list lights, toggle, scenes).
- Add discovery using huesdk’s discovery features to auto-detect bridge IP, falling back to env.
- Add CI workflow using uv for lock fidelity and a job that runs unit tests (no network).
