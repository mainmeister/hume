# Improvement Tasks Checklist

A logically ordered, actionable plan to evolve the "hume" project from a single-script prototype to a minimal, testable Hue control utility. Check items off as you complete them.

1. [ ] Establish project basics
   - [ ] Add a README with quickstart, environment variables, and basic usage (uv sync, uv run python main.py).
   - [ ] Document required environment variables: HUE_USER_ID (required), HUE_BRIDGE_IP (optional; default to current hard-coded IP until refactor).
   - [ ] Add a simple CONTRIBUTING.md describing development flow (uv, tests, style).

2. [ ] Refactor runtime side-effects into a proper entrypoint
   - [ ] Move import-time logic in main.py into functions and a main() entrypoint.
   - [ ] Protect runtime behavior with if __name__ == "__main__": to avoid side effects on import.

3. [ ] Improve configuration handling
   - [ ] Replace hard-coded BRIDGE_IP with environment variable HUE_BRIDGE_IP (default to 192.168.1.2).
   - [ ] Centralize configuration reading in a function (e.g., load_config()) with validation and helpful errors.

4. [ ] Modularize Hue logic
   - [ ] Implement build_base_url(user_id: str, bridge_ip: str) -> str.
   - [ ] Implement fetch_bridge_state(base_url: str, timeout: float = 5.0) with requests.get(..., timeout=timeout).
   - [ ] Separate data formatting (pretty JSON) from retrieval; return data instead of printing inside fetch.

5. [ ] Add logging and diagnostics
   - [ ] Replace print statements with logging configured via LOG_LEVEL env var (default INFO).
   - [ ] Add contextual logs for configuration, URL being fetched (without secrets), and operation outcomes.

6. [ ] Robust error handling
   - [ ] Catch requests.exceptions.RequestException; log error and exit non-zero in CLI path.
   - [ ] Handle JSON decoding errors gracefully with clear messaging.
   - [ ] Validate presence of HUE_USER_ID at runtime with actionable guidance.

7. [ ] Testing foundation (unittest)
   - [ ] Introduce tests/ package and basic unit tests for build_base_url and configuration loading.
   - [ ] Mock requests.get in tests for fetch_bridge_state to avoid network access.
   - [ ] Add integration tests guarded by env flag (INTEGRATION=1) and skipped by default.
   - [ ] Ensure tests can run via uv run python -m unittest discover -s tests -v.

8. [ ] Networking hygiene
   - [ ] Ensure all HTTP calls set a reasonable timeout (default 5 seconds; configurable).
   - [ ] Avoid performing network requests at import time (covered by entrypoint refactor).

9. [ ] CLI improvements (optional initial scope, prepare for future)
   - [ ] Introduce argparse-based CLI with subcommands (e.g., state, lights list) behind main().
   - [ ] Provide --bridge-ip and --timeout flags overriding env/config.

10. [ ] Type hints and interfaces
    - [ ] Add type hints to new functions (config, URL builder, fetchers).
    - [ ] Consider Protocols or TypedDicts for expected Hue responses (lightweight, optional).

11. [ ] Code quality tooling (optional but recommended)
    - [ ] Add ruff (lint) and black (format) to dev dependencies; document usage (uv run ruff, uv run black).
    - [ ] Add a simple pre-commit config or make target to run formatting/linting.

12. [ ] Dependency hygiene
    - [ ] Remove unused imports (e.g., huesdk Hue if not used yet) or use it intentionally.
    - [ ] Ensure all runtime deps are declared in pyproject and uv.lock kept up to date (uv sync updates lock).

13. [ ] Packaging and structure
    - [ ] Consider moving logic into a package (e.g., hume/ with __init__.py) while keeping main.py as thin entrypoint.
    - [ ] Prepare for future CLI packaging (optional pyproject [project.scripts] entry).

14. [ ] Observability and UX
    - [ ] Standardize error messages and exit codes for CLI use.
    - [ ] Redact sensitive values (HUE_USER_ID) from logs; only show last 4 chars if needed.

15. [ ] Documentation updates
    - [ ] Update README with examples (setting env vars, running commands, sample outputs).
    - [ ] Add a TROUBLESHOOTING section (timeouts, missing env vars, unreachable bridge).

16. [ ] Continuous Integration (future)
    - [ ] Add a basic CI workflow using uv to install and run unit tests (no network).
    - [ ] Optionally add lint/format checks in CI job.

17. [ ] Discovery enhancement (future)
    - [ ] Evaluate huesdk discovery to auto-detect bridge IP; fall back to HUE_BRIDGE_IP env var.
    - [ ] Add a --discover flag or automatic first-run discovery with caching.

18. [ ] Security and secrets handling
    - [ ] Provide .env.example (without secrets) and document using direnv or exporting vars manually.
    - [ ] Ensure logs and errors never print full HUE_USER_ID.
